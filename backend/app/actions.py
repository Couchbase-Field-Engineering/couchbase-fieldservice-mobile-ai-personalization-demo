"""Field-service actions - the business logic behind every MCP tool.

These functions are what actually changes state (work orders, depot stock,
maintenance budget, recurring tasks, RMAs, outage windows, visit logs). They
are only ever reached through `tool_gateway`, which routes them through the
Couchbase Agent Operations Manager when it is configured (RBAC, approvals,
tracing, audit) and calls them in-process otherwise. Every mutation bumps the
site's `rev`, which is what invalidates that site's context cache and
re-ranks its work plan.

Every tool takes the calling technician's `tech_id`. The worker fills it from
the work-order document, which Sync Gateway only accepted from that signed-in
technician, and the assistant fills it from the app token; a site can only be
worked by a technician whose area it belongs to.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from . import catalog as C
from .docs import (site_id_doc, days_since, inventory_id, money, now_iso, tech_id_doc, area_channel,
                   today)
from .store import store


class ToolError(Exception):
    pass


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def load_site(site_id: str, tech_id: str | None = None) -> dict:
    a = await store.get("sites", site_id_doc(site_id))
    if not a:
        raise ToolError(f"No site '{site_id}'")
    if tech_id:
        tech = await store.get("techs", tech_id_doc(tech_id))
        if not tech or tech.get("area_id") != a.get("area_id"):
            raise ToolError(f"{site_id} is not in your area")
    return a


async def save_site(a: dict):
    a["rev"] = int(a.get("rev", 0)) + 1
    a["updated_at"] = now_iso()
    await store.upsert("sites", site_id_doc(a["site_id"]), a)
    from .loader import mark_live  # late import: loader -> personalization -> actions
    await mark_live(a["site_id"])


async def after_change(site_id: str):
    # late imports: personalization/assistant import this module
    from . import assistant, personalization
    await personalization.refresh_work_plan(site_id)
    await assistant.invalidate_context(site_id)


async def get_inventory(depot: str) -> tuple[dict, int]:
    doc, cas = await store.get_with_cas("inventory", inventory_id(depot))
    if doc is None:
        await store.insert("inventory", inventory_id(depot),
                           {"type": "inventory", "depot": depot, "depot_name": C.DEPOTS[depot]["name"],
                            "on_hand": C.initial_inventory(depot), "created_at": now_iso()})
        doc, cas = await store.get_with_cas("inventory", inventory_id(depot))
    return doc, cas


async def allocate_inventory(depot: str, wants: dict[str, int]) -> dict[str, int]:
    """Take what is on hand for each SKU (CAS-protected). Returns what was
    actually issued per SKU; the rest goes on order."""
    for _ in range(10):
        doc, cas = await get_inventory(depot)
        got = {}
        for sku, qty in wants.items():
            avail = max(0, int(doc["on_hand"].get(sku, 0)))
            got[sku] = min(avail, int(qty))
            doc["on_hand"][sku] = avail - got[sku]
        doc["updated_at"] = now_iso()
        if await store.replace_cas("inventory", inventory_id(depot), doc, cas):
            return got
    raise ToolError("Depot stock is busy - please try again")


def _line(sku: str, qty: int) -> dict:
    p = C.PRODUCT_BY_SKU.get(sku)
    if not p:
        raise ToolError(f"Unknown part '{sku}'")
    qty = int(qty)
    if qty < 1 or qty > 100:
        raise ToolError(f"Quantity for {p['name']} must be between 1 and 100")
    unit = C.part_cost(sku)
    return {"sku": sku, "name": p["name"], "category": p["category"], "uom": p["uom"], "qty": qty,
            "unit_cost": unit, "line_total": round(unit * qty, 2), "swap_min": p["swap_min"],
            "service_affecting": p["service_affecting"]}


def _normalize_lines(lines) -> list[dict]:
    if not isinstance(lines, list) or not lines:
        raise ToolError("A work order needs at least one part line")
    merged: dict[str, int] = {}
    for ln in lines:
        if not isinstance(ln, dict) or not ln.get("sku"):
            raise ToolError("Each line needs a sku and qty")
        merged[ln["sku"]] = merged.get(ln["sku"], 0) + int(ln.get("qty") or 1)
    return [_line(sku, qty) for sku, qty in merged.items()]


def _totals(lines: list[dict]) -> dict:
    parts = round(sum(l["line_total"] for l in lines), 2)
    return {"parts_usd": parts, "total_usd": parts, "swap_minutes": sum(l["swap_min"] * l["qty"] for l in lines),
            "service_affecting": any(l["service_affecting"] for l in lines)}


def auth_check(a: dict, total: float) -> dict:
    """Work authorization for a site: what is left of its maintenance budget
    this quarter, and whether the site is on an access hold."""
    c = a["auth"]
    available = round(c["budget_limit_usd"] + c.get("temporary_extension_usd", 0) - c["committed_usd"], 2)
    return {"budget_limit_usd": c["budget_limit_usd"], "committed_usd": c["committed_usd"],
            "temporary_extension_usd": c.get("temporary_extension_usd", 0), "available_usd": available,
            "on_hold": bool(c.get("on_hold")), "hold_days": c.get("hold_days", 0), "hold_reason": c.get("hold_reason"),
            "ok": not c.get("on_hold") and total <= available, "shortfall_usd": round(max(0, total - available), 2)}


def _business_days(days: int) -> str:
    d = today()
    while days:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d.isoformat()


def _next_work_order_id(a: dict) -> str:
    return f"WO-{today():%y%m%d}-{_h(a['site_id'], now_iso(), uuid.uuid4().hex) % 90000 + 10000}"


def _default_work_type(a: dict) -> str:
    """Corrective when the site has a major or critical alarm open, preventive otherwise."""
    if any(al.get("severity") in ("critical", "major") for al in a.get("alarms", [])):
        return C.WORK_TYPES[1]
    return C.WORK_TYPES[0]


# --------------------------------------------------------------------------
# read-only tools
# --------------------------------------------------------------------------
async def get_site_context(tech_id: str, site_id: str) -> dict:
    a = await load_site(site_id, tech_id)
    last = a["work_history"][0] if a.get("work_history") else None
    return {
        "site_id": site_id, "site_name": a["site_name"], "site_code": a.get("site_code"), "site_type": a["site_type_name"],
        "cluster": a.get("cluster"), "address": a["address"], "contacts": a.get("contacts", []),
        "sla": a["sla"], "auth": auth_check(a, 0.0), "access": a["access"],
        "visit": a["visit"], "alarms": a.get("alarms", []), "assets": a.get("assets", []), "kpis": a.get("kpis", {}),
        "last_work_order": last, "days_since_last_work_order": days_since(last["date"]) if last else None,
        "maintenance": a.get("maintenance", {}), "recurring_tasks": a.get("recurring_tasks", []),
        "outage_windows": a.get("outage_windows", []),
        "segment": a["ml_scores"].get("segment"), "next_best_action": a["ml_scores"].get("next_best_action"),
        "outage_risk": a["ml_scores"].get("outage_risk"),
    }


async def get_work_plan(tech_id: str, site_id: str) -> dict:
    """The asset-health model's recommended work for this site: parts to
    replace, checked against the serving depot's on-hand units and the
    site's maintenance budget, plus the corrective and preventive tasks."""
    from .personalization import plan_tasks  # avoid import cycle

    a = await load_site(site_id, tech_id)
    inv, _ = await get_inventory(a["access"]["depot"])
    lines = []
    for s in a["ml_scores"].get("recommended_parts", []):
        if s["sku"] not in C.PRODUCT_BY_SKU:
            continue
        ln = _line(s["sku"], s["qty"])
        w = a.get("wear", {}).get(s["sku"], {})
        ln.update({"confidence": s.get("confidence"), "reason": s.get("reason"),
                   "days_since_replaced": days_since(w.get("last_replaced")),
                   "days_to_failure": a["ml_scores"].get("days_to_failure", {}).get(s["sku"]),
                   "on_hand_at_depot": inv["on_hand"].get(s["sku"], 0)})
        lines.append(ln)
    tot = _totals(lines) if lines else {}
    return {"site_id": site_id, "site_name": a["site_name"], "tier": a["sla"]["tier"],
            "work_type": _default_work_type(a), "depot": a["access"]["depot"], "lines": lines, "totals": tot,
            "tasks": plan_tasks(a), "alarms": a.get("alarms", []),
            "auth": auth_check(a, tot.get("total_usd", 0.0)),
            "upgrades": [dict(_line(s, 1), reason="Model upgrade candidate") for s in a["ml_scores"].get("upgrade_skus", [])
                         if s in C.PRODUCT_BY_SKU][:3],
            "model_version": a["ml_scores"].get("model_version")}


async def search_parts(tech_id: str, site_id: str, query: str = "", category: str = "") -> dict:
    a = await load_site(site_id, tech_id)
    inv, _ = await get_inventory(a["access"]["depot"])
    q = (query or "").lower().split()
    out = []
    for p in C.PRODUCTS:
        if category and p["category"] != category:
            continue
        hay = f"{p['name']} {p['sku']} {' '.join(p['tags'])} {C.CATEGORIES[p['category']]['name']}".lower()
        score = sum(1 for w in q if w in hay)
        if q and not score:
            continue
        w = a.get("wear", {}).get(p["sku"])
        out.append({**_line(p["sku"], 1), "on_hand_at_depot": inv["on_hand"].get(p["sku"], 0),
                    "fitted_here": bool(w), "per_year": (w or {}).get("per_year"),
                    "last_replaced": (w or {}).get("last_replaced"), "score": score + (0.5 if w else 0)})
    out.sort(key=lambda r: (-r["score"], r["name"]))
    return {"site_id": site_id, "items": out[:15]}


async def quote_work_order(tech_id: str, site_id: str, lines: list) -> dict:
    a = await load_site(site_id, tech_id)
    ls = _normalize_lines(lines)
    tot = _totals(ls)
    inv, _ = await get_inventory(a["access"]["depot"])
    short = [{"sku": l["sku"], "name": l["name"], "requested": l["qty"], "on_hand": inv["on_hand"].get(l["sku"], 0)}
             for l in ls if inv["on_hand"].get(l["sku"], 0) < l["qty"]]
    return {"site_id": site_id, "lines": ls, "totals": tot, "auth": auth_check(a, tot["total_usd"]),
            "short": short, "depot": a["access"]["depot"]}


# --------------------------------------------------------------------------
# mutating tools
# --------------------------------------------------------------------------
async def submit_work_order(tech_id: str, site_id: str, lines: list, ticket: str = "", work_type: str = "",
                            notes: str = "", tasks_done: list | None = None, _override: bool = False) -> dict:
    a = await load_site(site_id, tech_id)
    ls = _normalize_lines(lines)
    wtype = work_type or _default_work_type(a)
    if wtype not in C.WORK_TYPES:
        raise ToolError(f"Work type must be one of: {', '.join(C.WORK_TYPES)}")
    tot = _totals(ls)
    auth = auth_check(a, tot["total_usd"])
    if auth["on_hold"]:
        return {"ok": False, "status": "failed", "reason_code": "site_hold", "auth": auth,
                "summary": f"{a['site_name']} is on an access hold ({auth['hold_days']} days: "
                           f"{auth.get('hold_reason') or 'see site notes'}). The Site Access desk has to release the hold "
                           "before work can be booked here."}
    if not auth["ok"] and not _override:
        return {"ok": False, "status": "failed", "reason_code": "budget_limit", "auth": auth, "totals": tot,
                "summary": f"This {money(tot['total_usd'])} work order exceeds {a['site_name']}'s remaining maintenance budget "
                           f"({money(auth['available_usd'])} of a {money(auth['budget_limit_usd'])} quarterly limit). "
                           f"A budget override of {money(auth['shortfall_usd'])} needs a Field Ops approval."}

    depot = a["access"]["depot"]
    got = await allocate_inventory(depot, {l["sku"]: l["qty"] for l in ls})
    backordered = []
    for l in ls:
        l["issued_qty"] = got[l["sku"]]
        l["backordered_qty"] = l["qty"] - got[l["sku"]]
        if l["backordered_qty"]:
            backordered.append({"sku": l["sku"], "name": l["name"], "qty": l["backordered_qty"],
                                "eta": (today() + dt.timedelta(days=3 + _h(depot, l["sku"]) % 7)).isoformat()})
    work_order_id = _next_work_order_id(a)
    status = "parts_pending" if backordered else "completed"
    done = [str(t)[:120] for t in (tasks_done or [])][:20]
    order = {"work_order_id": work_order_id, "date": today().isoformat(), "closed_at": now_iso(), "status": status,
             "source": "field_tech", "tech_id": tech_id, "ticket": (ticket or "").strip()[:40],
             "work_type": wtype, "depot": depot, "notes": (notes or "").strip()[:300],
             "follow_up_date": max(b["eta"] for b in backordered) if backordered else None,
             "lines": ls, "line_count": len(ls), **tot, "tasks_done": done, "backordered": backordered,
             "budget_override": _override}
    # live state on the site: committed budget, history, wear clocks, cleared alarms, temporary budget used up
    a["auth"]["committed_usd"] = round(a["auth"]["committed_usd"] + tot["total_usd"], 2)
    if _override:
        a["auth"]["temporary_extension_usd"] = 0
        a["auth"]["last_override"] = {"work_order_id": work_order_id, "amount_usd": auth["shortfall_usd"], "at": now_iso()}
    a["work_history"] = ([order] + a.get("work_history", []))[:24]
    fitted_cats = set()
    for l in ls:
        if not l["issued_qty"]:
            continue
        fitted_cats.add(l["category"])
        w = a.setdefault("wear", {}).setdefault(l["sku"], {"per_year": float(l["qty"])})
        w["last_replaced"] = today().isoformat()
        w["last_qty"] = l["qty"]
    # A fitted part clears the open alarms in its category and lifts the asset's health score.
    cleared = [al for al in a.get("alarms", []) if al.get("category") in fitted_cats]
    a["alarms"] = [al for al in a.get("alarms", []) if al.get("category") not in fitted_cats]
    for asset in a.get("assets", []):
        if asset.get("category") in fitted_cats:
            asset["health"] = max(int(asset.get("health", 80)), 92)
            asset["status"] = "ok"
    mt = a.setdefault("maintenance", {})
    mt["ytd_usd"] = round(mt.get("ytd_usd", 0) + tot["total_usd"], 2)
    mt["work_orders_last_12mo"] = mt.get("work_orders_last_12mo", 0) + 1
    await save_site(a)
    await after_change(site_id)
    bo = (f" {len(backordered)} part{'s' if len(backordered) > 1 else ''} on order: "
          + "; ".join(f"{b['name'].split(',')[0]} x{b['qty']} (ETA {b['eta']})" for b in backordered)
          + ". A follow-up visit is needed.") if backordered else ""
    al = f" {len(cleared)} alarm{'s' if len(cleared) != 1 else ''} cleared." if cleared else ""
    tk = f" {len(done)} checklist task{'s' if len(done) != 1 else ''} recorded." if done else ""
    return {"ok": True, "status": status, "cost_usd": tot["total_usd"], "item": order,
            "summary": f"Work order {work_order_id} closed for {a['site_name']}: {wtype.lower()}, {len(ls)} part line"
                       f"{'s' if len(ls) != 1 else ''}, {money(tot['total_usd'])} against the site budget, issued from "
                       f"{C.DEPOTS[depot]['name']}.{tk}{al}{bo}"}


async def request_budget_override(tech_id: str, site_id: str, lines: list, reason: str, ticket: str = "",
                                  work_type: str = "", notes: str = "", tasks_done: list | None = None) -> dict:
    """Book a work order above the site's remaining maintenance budget. Held
    for a Field Ops decision in AOM's approval tier before it can run; once
    approved the shortfall becomes a one-time budget extension and the work
    order is closed."""
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A budget override needs a reason for the audit trail")
    a = await load_site(site_id, tech_id)
    ls = _normalize_lines(lines)
    auth = auth_check(a, _totals(ls)["total_usd"])
    if auth["on_hold"]:
        raise ToolError(f"{a['site_name']} is on an access hold - an override can't release a hold")
    if auth["ok"]:
        # Nothing to override; just book it.
        return await submit_work_order(tech_id, site_id, lines, ticket, work_type, notes, tasks_done)
    a["auth"]["temporary_extension_usd"] = auth["shortfall_usd"]
    a["auth"]["override_reason"] = reason.strip()[:300]
    await save_site(a)
    res = await submit_work_order(tech_id, site_id, lines, ticket, work_type,
                                  notes or f"Budget override approved: {reason.strip()[:120]}", tasks_done, _override=True)
    if res.get("ok"):
        res["summary"] = (f"Budget override of {money(auth['shortfall_usd'])} approved by Field Ops. "
                          + res["summary"])
        res["item"]["budget_override_usd"] = auth["shortfall_usd"]
    return res


async def set_recurring_task(tech_id: str, site_id: str, sku: str, qty: int, cadence_weeks: int = 12) -> dict:
    a = await load_site(site_id, tech_id)
    ln = _line(sku, qty)
    if not C.PRODUCT_BY_SKU[sku]["wear_item"]:
        raise ToolError("Recurring replacement is for wear items (filters, batteries, optics, kits)")
    cadence = int(cadence_weeks)
    if cadence not in (2, 4, 8, 12, 26, 52):
        raise ToolError("Cadence must be 2, 4, 8, 12, 26 or 52 weeks")
    so = {"sku": sku, "name": ln["name"], "qty": ln["qty"], "unit_cost": ln["unit_cost"], "cadence_weeks": cadence,
          "next_date": (today() + dt.timedelta(weeks=cadence)).isoformat(), "created_at": now_iso(), "created_by": tech_id}
    a["recurring_tasks"] = [s for s in a.get("recurring_tasks", []) if s["sku"] != sku] + [so]
    await save_site(a)
    await after_change(site_id)
    return {"ok": True, "status": "completed", "cost_usd": 0, "item": {**so, "kind": "recurring_task"},
            "summary": f"Recurring task set: replace {ln['qty']} x {ln['name'].split(',')[0]} every {cadence} week"
                       f"{'s' if cadence > 1 else ''} at {a['site_name']}, next on {so['next_date']}."}


async def create_rma(tech_id: str, site_id: str, work_order_id: str, sku: str, qty: int, reason: str) -> dict:
    a = await load_site(site_id, tech_id)
    order = next((o for o in a.get("work_history", []) if o.get("work_order_id") == work_order_id), None)
    if not order:
        raise ToolError(f"Work order {work_order_id} isn't in {a['site_name']}'s recent history")
    if days_since(order["date"]) > 30:
        raise ToolError("Parts can be returned within 30 days of being issued")
    line = next((l for l in order.get("lines", []) if l["sku"] == sku), None)
    if not line:
        raise ToolError(f"{sku} wasn't on work order {work_order_id}")
    qty = int(qty)
    if qty < 1 or qty > line["qty"]:
        raise ToolError(f"Return quantity must be between 1 and {line['qty']}")
    if not reason or len(reason.strip()) < 3:
        raise ToolError("An RMA needs a reason")
    refund = round(line["unit_cost"] * qty, 2)
    rma = {"rma_id": f"RMA-{_h(work_order_id, sku, now_iso()) % 900000 + 100000}", "work_order_id": work_order_id, "sku": sku,
           "name": line["name"], "qty": qty, "refund_usd": refund, "reason": reason.strip()[:200], "date": today().isoformat(),
           "return_by": _business_days(5), "kind": "rma"}
    a["auth"]["committed_usd"] = round(max(0.0, a["auth"]["committed_usd"] - refund), 2)
    a["rmas"] = ([rma] + a.get("rmas", []))[:12]
    await save_site(a)
    await after_change(site_id)
    return {"ok": True, "status": "completed", "cost_usd": -refund, "item": rma,
            "summary": f"{rma['rma_id']} created: {qty} x {line['name'].split(',')[0]} from {work_order_id}, "
                       f"{money(refund)} credited back to the site budget. Return the part to the depot by {rma['return_by']}."}


async def log_site_visit(tech_id: str, site_id: str, outcome: str, notes: str = "", next_visit_days: int = 0) -> dict:
    a = await load_site(site_id, tech_id)
    outcomes = ("work_completed", "no_fault_found", "follow_up", "no_access")
    if outcome not in outcomes:
        raise ToolError(f"Outcome must be one of: {', '.join(outcomes)}")
    cadence = int(next_visit_days or a["visit"].get("cadence_days") or 30)
    a["visit"]["last_visit"] = today().isoformat()
    a["visit"]["last_outcome"] = outcome
    a["visit"]["next_visit_date"] = (today() + dt.timedelta(days=cadence)).isoformat()
    a["visit"]["notes"] = (notes or "").strip()[:300]
    await save_site(a)
    # Mark the stop on the technician's route.
    tech = await store.get("techs", tech_id_doc(tech_id))
    if tech:
        for stop in tech.get("route", []):
            if stop["site_id"] == site_id:
                stop["status"] = "visited"
                stop["outcome"] = outcome
                stop["visited_at"] = now_iso()
        tech["rev"] = int(tech.get("rev", 0)) + 1
        tech["updated_at"] = now_iso()
        await store.upsert("techs", tech_id_doc(tech_id), tech)
    await after_change(site_id)
    item = {"kind": "visit", "site_id": site_id, "outcome": outcome, "date": today().isoformat(),
            "next_visit_date": a["visit"]["next_visit_date"], "notes": a["visit"]["notes"]}
    return {"ok": True, "status": "completed", "cost_usd": 0, "item": item,
            "summary": f"Visit logged for {a['site_name']} ({outcome.replace('_', ' ')}). Next visit {item['next_visit_date']}."}


async def request_outage_window(tech_id: str, site_id: str, duration_min: int, reason: str) -> dict:
    """A planned service-affecting window at a site (taking a sector, a link
    or the whole site off-air to swap hardware). Held for a NOC decision in
    AOM's approval tier before it is granted."""
    a = await load_site(site_id, tech_id)
    mins = int(duration_min)
    if mins < 5 or mins > 240:
        raise ToolError("Outage windows are between 5 and 240 minutes")
    if not reason or len(reason.strip()) < 5:
        raise ToolError("An outage window needs a reason for the audit trail")
    if a["auth"].get("on_hold"):
        raise ToolError(f"{a['site_name']} is on an access hold - no window can be granted until it is released")
    item = {"kind": "outage_window", "window_id": f"OW-{_h(site_id, now_iso()) % 900000 + 100000}", "duration_min": mins,
            "reason": reason.strip()[:200], "date": today().isoformat(), "granted_at": now_iso(), "requested_by": tech_id,
            "restore_target_hours": a["sla"].get("restore_hours")}
    a["outage_windows"] = ([item] + a.get("outage_windows", []))[:12]
    await save_site(a)
    await after_change(site_id)
    return {"ok": True, "status": "completed", "cost_usd": 0, "item": item,
            "summary": f"Outage window {item['window_id']} granted by the NOC for {a['site_name']}: {mins} minutes, today. "
                       f"Reason recorded: {reason.strip()[:120]}"}


TOOLS = {
    "get_site_context": get_site_context,
    "get_work_plan": get_work_plan,
    "search_parts": search_parts,
    "quote_work_order": quote_work_order,
    "submit_work_order": submit_work_order,
    "request_budget_override": request_budget_override,
    "set_recurring_task": set_recurring_task,
    "create_rma": create_rma,
    "log_site_visit": log_site_visit,
    "request_outage_window": request_outage_window,
}
READ_ONLY_TOOLS = {"get_site_context", "get_work_plan", "search_parts", "quote_work_order"}
APPROVAL_TOOLS = ["request_budget_override", "request_outage_window"]


def area_channels(a: dict) -> list[str]:
    return [area_channel(a["area_id"])]
