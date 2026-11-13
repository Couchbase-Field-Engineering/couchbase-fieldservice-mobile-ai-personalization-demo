"""Daily Databricks export -> Couchbase + AOM Knowledge Base.

Run by the backend on startup and every DUMP_POLL_SECONDS (it only does work
when a newer `dt=YYYY-MM-DD/_SUCCESS` partition appears), or by hand:

    python -m app.loader [--dump-dir PATH] [--force] [--no-kb]

1. Stream every JSON Lines part file of the newest complete partition.
2. Upsert one `sites` document per network site (all ~100MB in
   Couchbase mode). Live state that changed since the last export (work orders
   closed, alarms cleared, budget committed, recurring tasks, visit logs) is carried forward - in
   production that state would already be in the next Databricks export.
3. Build one `techs` document per field technician (area, today's route), index
   employee ids for login, publish the catalog, and build the work plan
   for every site due for a visit soon.
4. Publish to the AOM Knowledge Base: the Field Maintenance Runbook, and one
   profile document per site due for a visit within KB_WINDOW_DAYS (demo
   areas first), replacing yesterday's version of each. The assistant's
   AOM RAG Application is then re-scoped to the new runbook document.

Context caches need no sweep: every cached context records the export date it
was built from, so the new export makes them all stale at once.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import glob
import json
import logging
import os
import time

from . import catalog as C
from . import config, knowledge, personalization, rag_app
from .aom_client import AOMError, aom
from .docs import (CATALOG_CHANNEL, CATALOG_ID, STATE, site_id_doc, now_iso, tech_channel, tech_id_doc,
                   area_channel)
from .store import store

log = logging.getLogger("fs.loader")
PERSONAS = ["T1001", "T1002", "T1003"]            # demo techs (employee ids 204817, 318552, 427190)
PERSONA_AREAS = ["A-BOS-NS", "A-NY-HV", "A-TX-DFW"]
LIVE_FIELDS = ("work_history", "wear", "recurring_tasks", "rmas", "outage_windows", "maintenance", "alarms", "assets")
SUGGEST_WINDOW_DAYS = 14
STATUS = {"state": "idle"}
_TASKS: list = []  # keep a reference so background KB publishing is not garbage-collected


def latest_partition(dump_dir: str) -> str | None:
    parts = sorted(p for p in glob.glob(os.path.join(dump_dir, "dt=*")) if os.path.exists(os.path.join(p, "_SUCCESS")))
    return parts[-1] if parts else None


def read_rows(partition: str):
    for path in sorted(glob.glob(os.path.join(partition, "part-*.json"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


async def mark_live(site_id: str):
    """Called after an action - remembers which sites have state newer than the export."""
    doc = await store.get("lookups", "live_sites") or {"sites": []}
    if site_id not in doc["sites"]:
        doc["sites"].append(site_id)
        await store.upsert("lookups", "live_sites", doc)


def _stop(a: dict, plan: dict | None) -> dict:
    last = a["work_history"][0] if a.get("work_history") else None
    return {"site_id": a["site_id"], "site_name": a["site_name"], "site_type": a["site_type_name"],
            "address": a["address"], "planned_time": a["visit"].get("planned_time") or "09:00",
            "signal_note": a["visit"].get("signal_note"), "contact": (a.get("contacts") or [{}])[0].get("name"),
            "site_code": a.get("site_code"), "plan_total_usd": (plan or {}).get("plan_total_usd"), "tier": a["sla"]["tier"],
            "work_type": (plan or {}).get("work_type"), "alarm_count": len(a.get("alarms", [])),
            "worst_alarm": min((al.get("severity") for al in a.get("alarms", [])), key=lambda s: {"critical": 0, "major": 1, "minor": 2}.get(s, 3), default=None),
            "outage_risk": a["ml_scores"].get("outage_risk"),
            "last_work_date": last["date"] if last else None, "hold_flag": bool(a["auth"].get("on_hold")),
            "status": "visited" if a["visit"].get("last_visit") == a["visit"].get("next_visit_date") else "planned"}


async def build_tech(tech: dict, sites: list[dict], today: dt.date) -> dict:
    prev = await store.get("techs", tech_id_doc(tech["tech_id"])) or {}
    due = [a for a in sites if a["visit"].get("next_visit_date") == today.isoformat()]
    due.sort(key=lambda a: a["visit"].get("planned_time") or "09:00")
    stops = []
    for a in due:
        plan = await store.get("work_plans", f"plan::{a['site_id']}")
        stop = _stop(a, plan)
        old = next((s for s in prev.get("route", []) if s["site_id"] == a["site_id"]), None)
        if old and prev.get("route_date") == today.isoformat() and old.get("status") == "visited":
            stop.update(status="visited", outcome=old.get("outcome"), visited_at=old.get("visited_at"))
        stops.append(stop)
    terr = C.AREAS.get(tech["area_id"], {})
    return {
        "type": "tech", **tech, "area_name": terr.get("name", tech.get("area_name")),
        "site_count": len(sites), "route_date": today.isoformat(), "route": stops,
        "due_this_week": sum(1 for a in sites if 0 <= (dt.date.fromisoformat(a["visit"]["next_visit_date"]) - today).days <= 6),
        "committed_usd": round(sum(a["auth"]["committed_usd"] for a in sites), 2),
        "on_hold_sites": sum(1 for a in sites if a["auth"].get("on_hold")),
        "open_alarms": sum(len(a.get("alarms", [])) for a in sites),
        "rev": int(prev.get("rev", 0)) + 1, "export_date": STATE.get("export_date"), "updated_at": now_iso(),
        "channels": [tech_channel(tech["tech_id"])],
    }


async def load(dump_dir: str | None = None, force=False, kb=True) -> dict:
    dump_dir = os.path.abspath(dump_dir or config.DUMP_DIR)
    part = latest_partition(dump_dir)
    if not part:
        log.warning("No complete Databricks partition (dt=*/_SUCCESS) under %s", dump_dir)
        STATUS.update(state="no_dump", dump_dir=dump_dir)
        return STATUS
    export_date = os.path.basename(part).split("=", 1)[1]
    state = await store.get("lookups", "load_state") or {}
    if state.get("export_date") == export_date and not force and state.get("driver") == store.driver and store.driver == "couchbase":
        STATE["export_date"] = export_date
        STATUS.update(state="loaded", **state)
        log.info("Export %s already loaded", export_date)
        pb = await store.get("lookups", "kbdoc::runbook") or {}
        if kb and config.KB_ENABLED and aom.admin_enabled and pb.get("export_date") != export_date:
            _TASKS.append(asyncio.create_task(publish_kb(export_date, await _kb_window())))
        elif kb and aom.admin_enabled and pb.get("document_id"):
            _TASKS.append(asyncio.create_task(rag_app.sync(pb["document_id"])))
        return STATUS

    t0 = time.time()
    STATE["export_date"] = export_date
    STATUS.update(state="loading", export_date=export_date, partition=part, started_at=now_iso())
    live = set((await store.get("lookups", "live_sites") or {}).get("sites", []))
    today = dt.date.fromisoformat(config.DEMO_TODAY or export_date)
    techs: dict[str, dict] = {}
    by_area: dict[str, list[dict]] = {}
    batch: dict[str, dict] = {}
    rows = skipped = carried = 0
    suggest: list[tuple[int, str]] = []
    nbytes = sum(os.path.getsize(p) for p in glob.glob(os.path.join(part, "part-*.json")))

    for row in read_rows(part):
        aid = row["site_id"]
        tid = row["area_id"]
        days_to_visit = (dt.date.fromisoformat(row["visit"]["next_visit_date"]) - today).days
        if store.driver == "memory" and days_to_visit > config.MEMORY_WINDOW_DAYS and tid not in PERSONA_AREAS:
            skipped += 1
            continue
        doc = {**row, "type": "site", "rev": 0, "channels": [area_channel(tid)], "loaded_at": now_iso()}
        if aid in live:
            prev = await store.get("sites", site_id_doc(aid))
            if prev:
                for f in LIVE_FIELDS:
                    if f in prev:
                        doc[f] = prev[f]
                doc["auth"] = {**doc["auth"], **{k: prev["auth"][k] for k in ("committed_usd", "temporary_extension_usd",
                                                                                  "last_override") if k in prev["auth"]}}
                for f in ("last_visit", "next_visit_date", "last_outcome", "notes"):
                    if f in prev.get("visit", {}):
                        doc["visit"][f] = prev["visit"][f]
                doc["rev"] = int(prev.get("rev", 0)) + 1
                carried += 1
        batch[site_id_doc(aid)] = doc
        tech = row["assigned_tech"]
        techs.setdefault(tech["tech_id"], {**tech, "area_id": tid})
        by_area.setdefault(tid, []).append(doc)
        if days_to_visit <= SUGGEST_WINDOW_DAYS or tid in PERSONA_AREAS:
            suggest.append((days_to_visit, aid))
        rows += 1
        if len(batch) >= 1000:
            await store.upsert_many("sites", batch)
            batch = {}
            STATUS["rows"] = rows
    await store.upsert_many("sites", batch)

    cat = C.public_catalog()
    cat.update({"type": "catalog", "faq": [{"q": f["q"], "a": f["a"], "keywords": f["keywords"]} for f in knowledge.FAQ],
                "export_date": export_date, "channels": [CATALOG_CHANNEL], "updated_at": now_iso()})
    await store.upsert("catalog", CATALOG_ID, cat)

    for _, aid in sorted(suggest):
        await personalization.refresh_work_plan(aid)

    logins = {}
    for rid, tech in techs.items():
        rdoc = await build_tech(tech, by_area.get(tech["area_id"], []), today)
        await store.upsert("techs", tech_id_doc(rid), rdoc)
        logins[f"login::{tech['employee_id']}"] = {"type": "login_index", "tech_id": rid, "last_name": tech["last_name"].lower(),
                                                  "area_id": tech["area_id"]}
    await store.upsert_many("lookups", logins)

    summary = {"export_date": export_date, "partition": part, "rows": rows, "techs": len(techs), "areas": len(by_area),
               "skipped_outside_window": skipped, "carried_live_state": carried, "bytes": nbytes,
               "work_plans_built": len(suggest), "load_seconds": round(time.time() - t0, 1),
               "driver": store.driver, "loaded_at": now_iso()}
    await store.upsert("lookups", "load_state", summary)
    STATUS.update(state="loaded", **summary)
    log.info("Loaded export %s: %s sites (%s techs) in %.1fs", export_date, rows, len(techs), time.time() - t0)

    if kb and config.KB_ENABLED and aom.admin_enabled:
        _TASKS.append(asyncio.create_task(publish_kb(export_date, await _kb_window())))
    elif kb and config.KB_ENABLED:
        STATUS["kb"] = {"state": "skipped", "reason": "AOM_URL / AOM_ADMIN_PASSWORD not set"}
    return STATUS


async def refresh_tech(tech_id: str):
    """Rebuild a tech's route document (after a work order or visit changes a stop)."""
    tech = await store.get("techs", tech_id_doc(tech_id))
    if not tech:
        return None
    sites = await store.sites_in_area(tech["area_id"])
    base = {k: tech[k] for k in ("tech_id", "employee_id", "first_name", "last_name", "email", "area_id", "area_name") if k in tech}
    doc = await build_tech(base, sites, dt.date.fromisoformat(config.DEMO_TODAY or STATE["export_date"]))
    await store.upsert("techs", tech_id_doc(tech_id), doc)
    return doc


async def _replace_kb_doc(key: str, title: str, content: str, metadata: dict):
    prev = await store.get("lookups", f"kbdoc::{key}")
    res = await aom.kb_ingest(title, content, metadata)
    new_id = res["document"]["document_id"]
    await store.upsert("lookups", f"kbdoc::{key}", {"type": "kb_index", "document_id": new_id, "title": title,
                                                    "export_date": metadata.get("export_date"), "at": now_iso()})
    if prev and prev.get("document_id") and prev["document_id"] != new_id:
        await aom.kb_delete(prev["document_id"])
    return new_id


async def publish_kb(export_date: str, site_ids: list[str]):
    t0 = time.time()
    STATUS["kb"] = {"state": "publishing", "total": len(site_ids) + 1, "done": 0, "errors": 0}
    try:
        runbook_id = await _replace_kb_doc("runbook", f"Field Maintenance Runbook {export_date}",
                                            knowledge.runbook_markdown(export_date),
                                            {"type": "runbook", "export_date": export_date, "pii": False})
        STATUS["kb"]["done"] += 1
        await rag_app.sync(runbook_id)
    except AOMError as exc:
        log.error("KB runbook publish failed: %s", exc)
        STATUS["kb"].update(state="error", error=str(exc)[:300])
        return
    sem = asyncio.Semaphore(4)

    async def one(aid):
        async with sem:
            a = await store.get("sites", site_id_doc(aid))
            if not a:
                return
            try:
                await _replace_kb_doc(aid, f"Site profile {aid} {export_date}", knowledge.site_profile_markdown(a),
                                      {"type": "site_profile", "site_id": aid, "export_date": export_date,
                                       "area_id": a["area_id"], "pii": True})
                STATUS["kb"]["done"] += 1
            except AOMError as exc:
                STATUS["kb"]["errors"] += 1
                log.warning("KB publish for %s failed: %s", aid, exc)

    await asyncio.gather(*(one(a) for a in site_ids))
    STATUS["kb"].update(state="published", seconds=round(time.time() - t0, 1), export_date=export_date)
    log.info("Published %d KB documents to AOM in %.1fs", STATUS["kb"]["done"], time.time() - t0)


async def poll_forever():
    while True:
        await asyncio.sleep(config.DUMP_POLL_SECONDS)
        try:
            part = latest_partition(os.path.abspath(config.DUMP_DIR))
            if part and os.path.basename(part).split("=", 1)[1] != STATE.get("export_date"):
                log.info("New Databricks partition detected: %s", part)
                await load()
        except Exception as exc:  # noqa: BLE001
            log.warning("dump poll failed: %s", exc)


async def _kb_window() -> list[str]:
    """KB targets: today's stops in the demo areas first, then every
    site due for a visit within KB_WINDOW_DAYS."""
    today = dt.date.fromisoformat(config.DEMO_TODAY or STATE["export_date"])
    end = (today + dt.timedelta(days=config.KB_WINDOW_DAYS)).isoformat()
    out: list[str] = []
    for rid in PERSONAS:
        tech = await store.get("techs", tech_id_doc(rid))
        out += [s["site_id"] for s in (tech or {}).get("route", []) if s["site_id"] not in out]
    if store.driver == "memory":
        rows = sorted((a["visit"]["next_visit_date"], a["site_id"]) for a in store.data["sites"].values()
                      if today.isoformat() <= a["visit"]["next_visit_date"] <= end)
        out += [aid for _, aid in rows if aid not in out]
    else:
        rows = await store._query(
            f"SELECT RAW a.site_id FROM {store._ks('sites')} a WHERE a.visit.next_visit_date >= $t "
            f"AND a.visit.next_visit_date <= $d ORDER BY a.visit.next_visit_date LIMIT $n",
            t=today.isoformat(), d=end, n=config.KB_PROFILE_LIMIT)
        out += [a for a in rows if a not in out]
    return out[: max(config.KB_PROFILE_LIMIT, len(out[:12]))]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-dir")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-kb", action="store_true")
    args = ap.parse_args()

    async def run():
        await store.connect()
        await load(args.dump_dir, force=args.force, kb=False)
        if not args.no_kb and config.KB_ENABLED and aom.admin_enabled:
            state = await store.get("lookups", "load_state")
            await publish_kb(state["export_date"], await _kb_window())
        print(json.dumps({k: v for k, v in STATUS.items()}, indent=2, default=str))

    asyncio.run(run())


if __name__ == "__main__":
    main()
