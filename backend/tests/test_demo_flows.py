"""End-to-end checks of the demo backend in memory mode (no Couchbase, no AOM).

    cd backend && pytest -q
"""
import os
import subprocess
import sys
import time
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = "2026-11-13"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    dump = tmp_path_factory.mktemp("dump")
    subprocess.run([sys.executable, os.path.join(ROOT, "databricks", "generate_mock_dump.py"),
                    "--export-date", EXPORT, "--target-mb", "3", "--out", str(dump)], check=True,
                   capture_output=True)
    os.environ.update(STORE_DRIVER="memory", DUMP_DIR=str(dump), AOM_URL="", SG_ADMIN_URL="")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        for _ in range(100):
            if c.get("/api/health").json()["load"] == "loaded":
                break
            time.sleep(0.1)
        yield c


def login(client, employee_id, last):
    r = client.post("/api/auth/login", json={"employee_id": employee_id, "last_name": last})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["tech_id"]


def pull(client, h):
    docs = client.get("/api/sync/pull", headers=h).json()["docs"]
    return {(d["collection"], d["id"]): d["doc"] for d in docs}


def push(client, h, tid, tool, args):
    oid = f"wo::{tid}::{uuid.uuid4().hex[:12]}"
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "work_orders", "id": oid, "doc": {
        "type": "request", "tech_id": tid, "tool": tool, "args": args, "site_id": args.get("site_id"),
        "created_at": f"{EXPORT}T15:00:00Z"}}]})
    assert r.status_code == 200, r.text
    for _ in range(50):
        d = pull(client, h).get(("work_orders", oid))
        if d and d["status"] not in ("pending", "processing"):
            return d
        time.sleep(0.1)
    raise AssertionError("work order never processed")


TOWER = "S00101001"          # Salem Harbor Tower: failing battery string, plan over budget
CENTRAL_OFFICE = "S00101002"  # Salem Central Office: needs rectifier modules, which are short everywhere
BATTERY, RECTIFIER, FILTER = "FS-PWR-2204", "FS-PWR-2101", "FS-CLG-3101"


def test_personas_and_login(client):
    ps = client.get("/api/demo/personas").json()["personas"]
    assert [p["tech_id"] for p in ps] == ["T1001", "T1002", "T1003"]
    assert ps[0]["stops_today"] == 5 and ps[2]["stops_today"] == 5
    assert client.post("/api/auth/login", json={"employee_id": "204817", "last_name": "Nope"}).status_code == 401


def test_route_and_work_plans_sync(client):
    h, tid = login(client, "204817", "Chen")
    docs = pull(client, h)
    tech = docs[("techs", f"tech::{tid}")]
    stops = [s["site_id"] for s in tech["route"]]
    assert stops == [TOWER, CENTRAL_OFFICE, "S00101003", "S00101004", "S00101005"]
    assert tech["route"][0]["signal_note"].startswith("Steel equipment shelter")
    assert tech["route"][0]["alarm_count"] == 2 and tech["route"][0]["worst_alarm"] == "major"
    plan = docs[("work_plans", f"plan::{TOWER}")]
    assert plan["lines"] and plan["lines"][0]["sku"] == BATTERY
    assert plan["lines"][0]["days_to_failure"] == 1 and plan["lines"][0]["availability"] == "low"  # 3 on hand, 4 wanted
    assert plan["work_type"] == "Corrective maintenance"  # a major alarm is open
    kinds = [t["kind"] for t in plan["tasks"]]
    assert kinds[0] == "corrective" and "preventive" in kinds  # corrective first, then the PM checklist
    assert not plan["auth"]["ok"] and plan["auth"]["shortfall_usd"] > 0  # the override story
    assert ("catalog", "catalog::v1") in docs
    # every site in the area syncs, nothing from another area
    assert all(d["area_id"] == "A-BOS-NS" for (c, _), d in docs.items() if c == "sites")


def test_work_order_over_budget_fails_then_override_closes_it(client):
    h, tid = login(client, "204817", "Chen")
    plan = pull(client, h)[("work_plans", f"plan::{TOWER}")]
    lines = [{"sku": l["sku"], "qty": l["qty"]} for l in plan["lines"] if l["selected"]]
    tasks = [t["title"] for t in plan["tasks"]]
    r = push(client, h, tid, "submit_work_order", {"site_id": TOWER, "lines": lines, "ticket": "INC-1042"})
    assert r["status"] == "failed" and r["reason_code"] == "budget_limit", r
    r = push(client, h, tid, "request_budget_override", {"site_id": TOWER, "lines": lines, "tasks_done": tasks,
                                                         "reason": "Battery string failing on a critical site"})
    assert r["status"] == "parts_pending", r  # one battery block is short at the Northeast depot
    assert r["item"]["budget_override"] is True and r["cost_usd"] > 1500
    assert r["item"]["backordered"][0]["sku"] == BATTERY and r["item"]["follow_up_date"]
    assert r["item"]["tasks_done"] == tasks
    docs = pull(client, h)
    site = docs[("sites", f"site::{TOWER}")]
    assert site["work_history"][0]["work_order_id"] == r["item"]["work_order_id"]
    assert site["auth"]["committed_usd"] > 8480.40
    assert site["alarms"] == []  # battery and filter fitted: both alarms cleared
    # the plan re-ranked: the parts just fitted are gone and the work is preventive again
    plan2 = docs[("work_plans", f"plan::{TOWER}")]
    assert not any(l["sku"] == BATTERY for l in plan2["lines"])
    assert plan2["work_type"] == "Preventive maintenance"


def test_short_depot_stock_puts_parts_on_order(client):
    h, tid = login(client, "204817", "Chen")
    # Every depot holds 1-3 rectifier modules; ask for more than it has.
    r = push(client, h, tid, "submit_work_order", {"site_id": CENTRAL_OFFICE, "lines": [{"sku": RECTIFIER, "qty": 5}]})
    assert r["status"] == "parts_pending", r
    assert r["item"]["backordered"][0]["sku"] == RECTIFIER


def test_assistant_context_cache_and_runbook(client):
    h, tid = login(client, "318552", "Walker")
    a = client.post("/api/assistant", headers=h, json={"message": "What needs doing at this site today?", "site_id": "S00102001"}).json()
    assert a["intent"] == "workplan" and a["personal"] and a["context"]["status"] == "miss"
    assert any(x.get("tool") == "submit_work_order" for x in a["actions"])
    b = client.post("/api/assistant", headers=h, json={"message": "Anything about to fail here?", "site_id": "S00102001"}).json()
    assert b["context"]["status"] == "hit"
    g = client.post("/api/assistant", headers=h, json={"message": "How does a budget override work?"}).json()
    assert g["personal"] is False and "field ops" in g["reply"].lower()
    s = client.post("/api/assistant", headers=h, json={"message": "What are the rules for climbing a tower?"}).json()
    assert s["personal"] is False and "rescue" in s["reply"].lower()
    n = client.post("/api/assistant", headers=h, json={"message": "What needs doing here?"}).json()
    assert n["personal"] and "route" in n["reply"].lower()  # no site open
    o = client.post("/api/assistant", headers=h, json={"message": "Do I need an outage window for this site?", "site_id": "S00102001"}).json()
    assert o["intent"] == "outage" and any(x.get("tool") == "request_outage_window" for x in o["actions"])
    assert ("context_cache", "ctx::S00102001::workplan") in pull(client, h)


def test_business_rules_and_access_hold(client):
    h, tid = login(client, "427190", "Alvarez")
    r = push(client, h, tid, "submit_work_order", {"site_id": "S00103020", "lines": [{"sku": BATTERY, "qty": 1}]})
    assert r["status"] == "failed" and r["reason_code"] == "site_hold"
    r = push(client, h, tid, "request_outage_window", {"site_id": "S00103020", "duration_min": 30, "reason": "Swap the surge cartridge"})
    assert r["status"] == "failed" and "hold" in r["summary"]
    r = push(client, h, tid, "set_recurring_task", {"site_id": "S00103001", "sku": "FS-FBR-7110", "qty": 1, "cadence_weeks": 12})
    assert r["status"] == "completed" and r["item"]["cadence_weeks"] == 12
    r = push(client, h, tid, "set_recurring_task", {"site_id": "S00103001", "sku": RECTIFIER, "qty": 1})
    assert r["status"] == "failed" and "wear" in r["summary"]
    r = push(client, h, tid, "submit_work_order", {"site_id": TOWER, "lines": [{"sku": FILTER, "qty": 1}]})
    assert r["status"] == "failed" and "area" in r["summary"]
    r = push(client, h, tid, "get_work_plan", {"site_id": "S00103001"})
    assert r["status"] == "failed"


def test_outage_window_is_recorded_on_the_site(client):
    h, tid = login(client, "427190", "Alvarez")
    r = push(client, h, tid, "request_outage_window", {"site_id": "S00103001", "duration_min": 20,
                                                       "reason": "Replace the fronthaul optic"})
    assert r["status"] == "completed" and r["item"]["duration_min"] == 20
    site = pull(client, h)[("sites", "site::S00103001")]
    assert site["outage_windows"][0]["window_id"] == r["item"]["window_id"]


def test_visit_log_marks_route_stop(client):
    h, tid = login(client, "427190", "Alvarez")
    r = push(client, h, tid, "log_site_visit", {"site_id": "S00103021", "outcome": "work_completed", "notes": "Generator fuel at 60%"})
    assert r["status"] == "completed"
    tech = pull(client, h)[("techs", f"tech::{tid}")]
    stop = next(s for s in tech["route"] if s["site_id"] == "S00103021")
    assert stop["status"] == "visited" and stop["outcome"] == "work_completed"


def test_rma_credits_the_site_budget(client):
    h, tid = login(client, "318552", "Walker")
    ok = push(client, h, tid, "submit_work_order", {"site_id": "S00102003", "lines": [{"sku": FILTER, "qty": 2}]})
    assert ok["status"] == "completed"
    before = pull(client, h)[("sites", "site::S00102003")]["auth"]["committed_usd"]
    r = push(client, h, tid, "create_rma", {"site_id": "S00102003", "work_order_id": ok["item"]["work_order_id"],
                                            "sku": FILTER, "qty": 1, "reason": "Wrong filter size"})
    assert r["status"] == "completed" and r["cost_usd"] < 0
    after = pull(client, h)[("sites", "site::S00102003")]["auth"]["committed_usd"]
    assert after < before


def test_push_rejects_other_techs(client):
    h, tid = login(client, "427190", "Alvarez")
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "work_orders", "id": "wo::T1001::x",
                                                                 "doc": {"tech_id": "T1001", "tool": "submit_work_order"}}]})
    assert r.status_code == 403


def test_databricks_offload_metrics(client):
    m = client.get("/api/status").json()["metrics"]
    assert m["warehouse_queries_avoided"] > 0 and m["estimated_dbx_spend_avoided_usd"] > 0
    assert m["work_orders_completed"] >= 3 and m["work_orders_queued_offline"] >= 1
