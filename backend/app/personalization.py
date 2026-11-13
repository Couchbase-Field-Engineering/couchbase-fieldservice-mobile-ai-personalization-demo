"""Builds the work plan for one site.

Inputs are the Databricks asset-health scores and wear profile from the daily
dump, plus live state the dump can't know about: work orders closed since
(parts fitted, alarms cleared, budget committed), on-hand units at the serving
depot, and what is left of the site's maintenance budget. The result is
written to `plan::<site_id>`, which Sync Gateway replicates to every
technician in the area - so the Work order screen renders from Couchbase
Lite, even inside a steel shelter with no signal, and re-ranks itself on the
next sync after every work order.

A plan has two halves: **corrective** work (the open alarms on the site) and
**preventive** work (the site type's PM checklist plus the parts the model
predicts are close to failure).
"""
from __future__ import annotations

from . import catalog as C
from .docs import site_id_doc, days_since, now_iso, plan_id, area_channel
from .store import store


def _reason(sku: str, a: dict, s: dict) -> str:
    w = a.get("wear", {}).get(sku, {})
    parts = []
    dsr = days_since(w.get("last_replaced"))
    dtf = (a["ml_scores"].get("days_to_failure") or {}).get(sku)
    if dtf is not None and dtf <= 0:
        parts.append("Predicted to have failed or be failing now")
    elif dtf is not None and dtf <= 14:
        parts.append(f"Predicted failure in about {dtf} day{'s' if dtf != 1 else ''}")
    elif dsr is not None:
        parts.append(f"Last replaced {dsr} days ago")
    if dsr is not None and dtf is not None and dtf <= 14:
        parts.append(f"in service {dsr} days")
    if s.get("reason"):
        parts.append(s["reason"])
    return " · ".join(parts[:3])


def plan_tasks(a: dict) -> list[dict]:
    """Corrective tasks from the site's open alarms, then the preventive
    checklist for its site type."""
    tasks = []
    order = {"critical": 0, "major": 1, "minor": 2}
    for al in sorted(a.get("alarms", []), key=lambda x: order.get(x.get("severity"), 3)):
        tasks.append({"id": f"cm-{al.get('alarm_id')}", "kind": "corrective", "severity": al.get("severity"),
                      "title": al.get("action") or f"Investigate and clear: {al.get('text')}",
                      "alarm": al.get("text"), "est_min": 30 if al.get("severity") == "minor" else 45})
    for i, title in enumerate(C.SITE_TYPES.get(a["site_type"], {}).get("pm", [])):
        tasks.append({"id": f"pm-{i + 1}", "kind": "preventive", "title": title, "est_min": 15})
    return tasks


async def compute_work_plan(a: dict) -> dict:
    from .actions import auth_check, get_inventory  # avoid import cycle

    s = a["ml_scores"]
    inv, _ = await get_inventory(a["access"]["depot"])
    lines = []
    recent = {l["sku"] for o in a.get("work_history", [])[:1] for l in o.get("lines", [])
              if days_since(o.get("date")) is not None and days_since(o.get("date")) <= 3}
    for rec in s.get("recommended_parts", []):
        sku = rec["sku"]
        p = C.PRODUCT_BY_SKU.get(sku)
        if not p or sku in recent:
            continue  # just fitted on this visit
        qty = int(rec["qty"])
        unit = C.part_cost(sku)
        on_hand = inv["on_hand"].get(sku, 0)
        cat_risk = s.get(C.CATEGORIES[p["category"]]["risk"], 0.5)
        score = float(rec.get("confidence", 0.5)) * (0.6 + 0.4 * cat_risk)
        dtf = (s.get("days_to_failure") or {}).get(sku)
        if dtf is not None and dtf <= 7:
            score *= 1.2
        lines.append({
            "sku": sku, "name": p["name"], "category": p["category"], "category_name": C.CATEGORIES[p["category"]]["name"],
            "uom": p["uom"], "spec": p["spec"], "qty": qty, "unit_cost": unit,
            "line_total": round(unit * qty, 2), "confidence": rec.get("confidence"), "reason": _reason(sku, a, rec),
            "on_hand_at_depot": on_hand, "availability": "in_stock" if on_hand >= qty else ("low" if on_hand > 0 else "backorder"),
            "days_to_failure": dtf, "swap_min": p["swap_min"], "service_affecting": p["service_affecting"],
            "score": round(score, 3), "selected": score >= 0.45,
        })
    lines.sort(key=lambda l: -l["score"])
    for i, l in enumerate(lines):
        l["rank"] = i + 1

    upgrades = []
    for sku in s.get("upgrade_skus", []):
        p = C.PRODUCT_BY_SKU.get(sku)
        if not p or any(l["sku"] == sku for l in lines):
            continue
        unit = C.part_cost(sku)
        upgrades.append({"sku": sku, "name": p["name"], "category": p["category"], "uom": p["uom"], "spec": p["spec"],
                         "qty": 1, "unit_cost": unit, "line_total": unit,
                         "reason": {"power": "Backup runtime below target for this SLA class",
                                    "radio": "Capacity trend from the traffic model",
                                    "tools": "Needed for the checks on this site type",
                                    "transport": "Backhaul utilisation trending up"}.get(p["category"], "Sites like this one carry it"),
                         "on_hand_at_depot": inv["on_hand"].get(sku, 0)})
    selected = [l for l in lines if l["selected"]]
    subtotal = round(sum(l["line_total"] for l in selected), 2)
    tasks = plan_tasks(a)
    corrective = any(al.get("severity") in ("critical", "major") for al in a.get("alarms", []))
    return {
        "lines": lines, "upgrades": upgrades[:3], "tasks": tasks,
        "work_type": C.WORK_TYPES[1] if corrective else C.WORK_TYPES[0],
        "alarms": a.get("alarms", []),
        "plan_total_usd": subtotal,
        "est_minutes": sum(t["est_min"] for t in tasks) + sum(l["swap_min"] * l["qty"] for l in selected),
        "service_affecting": any(l["service_affecting"] for l in selected),
        "auth": auth_check(a, subtotal),
        "briefing": briefing(a, lines),
    }


def briefing(a: dict, lines: list[dict]) -> list[str]:
    """What the technician should know before opening the cabinet."""
    s = a["ml_scores"]
    pts = []
    alarms = a.get("alarms", [])
    if alarms:
        worst = sorted(alarms, key=lambda x: {"critical": 0, "major": 1, "minor": 2}.get(x.get("severity"), 3))
        pts.append(f"{len(alarms)} open alarm{'s' if len(alarms) > 1 else ''}: "
                   + "; ".join(f"{al['severity']} - {al['text']}" for al in worst[:2]))
    urgent = [l for l in lines if l.get("days_to_failure") is not None and l["days_to_failure"] <= 7]
    if urgent:
        pts.append("Close to failure: " + ", ".join(l["name"].split(",")[0] for l in urgent[:3]))
    last = a["work_history"][0] if a.get("work_history") else None
    if last:
        pts.append(f"Last work order {last['work_order_id']} on {last['date']}: {last.get('work_type', 'maintenance').lower()}, "
                   f"{last.get('line_count', len(last.get('lines', [])))} parts, ${last['total_usd']:,.2f}"
                   + (" (parts were on order)" if last.get("backordered") else ""))
    c = a["auth"]
    if c.get("on_hold"):
        pts.append(f"Access hold for {c.get('hold_days', 0)} days - {c.get('hold_reason') or 'see site notes'}. "
                   "Clear it with the Site Access desk before starting.")
    elif c["committed_usd"] > 0.75 * c["budget_limit_usd"]:
        pts.append(f"${c['committed_usd']:,.0f} of the ${c['budget_limit_usd']:,.0f} quarterly maintenance budget is committed - "
                   "a large parts swap may need a budget override")
    if s.get("outage_risk", 0) >= 0.5:
        pts.append(f"Outage risk {s['outage_risk']:.0%} over the next 30 days - {a['sla']['tier_name']} site, "
                   f"{a['sla'].get('restore_hours')}h restore target")
    if a["access"].get("climb_required"):
        pts.append("Tower climb required - climb-certified crew and rescue kit")
    if a.get("recurring_tasks"):
        pts.append(f"{len(a['recurring_tasks'])} recurring task{'s' if len(a['recurring_tasks']) > 1 else ''} scheduled")
    return pts[:5]


async def refresh_work_plan(site_id: str) -> dict | None:
    a = await store.get("sites", site_id_doc(site_id))
    if not a:
        return None
    plan = await compute_work_plan(a)
    doc = {
        "type": "work_plan", "site_id": site_id, "site_name": a["site_name"], "area_id": a["area_id"],
        **plan,
        "model_version": a["ml_scores"].get("model_version"), "segment": a["ml_scores"].get("segment"),
        "outage_risk": a["ml_scores"].get("outage_risk"),
        "export_date": a.get("export_date"), "site_rev": a.get("rev", 0),
        "generated_at": now_iso(), "channels": [area_channel(a["area_id"])],
    }
    await store.upsert("work_plans", plan_id(site_id), doc)
    return doc
