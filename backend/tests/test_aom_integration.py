"""The AOM-governed path, against tests/fake_aom.py (same routes and shapes as
the real AOM): KB publishing, document-scoped retrieval, LLM cache across
techs, tool calls over real MCP, and the human-approval tier.
"""
import os
import subprocess
import sys
import time
import uuid

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
AOM, API = "http://127.0.0.1:18090", "http://127.0.0.1:18201"


def wait(url, tries=80):
    for _ in range(tries):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{url} never came up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    dump = tmp_path_factory.mktemp("dump")
    subprocess.run([sys.executable, os.path.join(ROOT, "databricks", "generate_mock_dump.py"), "--export-date",
                    "2026-11-13", "--target-mb", "2", "--out", str(dump)], check=True, capture_output=True)
    env = {**os.environ, "STORE_DRIVER": "memory", "DUMP_DIR": str(dump), "AOM_URL": AOM,
           "AOM_AGENT_API_KEY": "fake-agent-key", "AOM_ADMIN_PASSWORD": "x", "KB_PROFILE_LIMIT": "10",
           "SG_ADMIN_URL": "", "REQUEST_POLL_SECONDS": "0.3", "FAKE_MCP_URL": f"{API}/fs/mcp", "AOM_MCP_PUBLIC_URL": f"{API}/fs/mcp"}
    uv = [sys.executable, "-m", "uvicorn"]
    procs = [subprocess.Popen(uv + ["tests.fake_aom:app", "--port", "18090"], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    wait(f"{AOM}/api/health")
    procs.append(subprocess.Popen(uv + ["app.main:app", "--port", "18201"], cwd=BACKEND, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(f"{API}/api/health")
    for _ in range(60):
        st = httpx.get(f"{API}/api/status").json()
        if (st["load"].get("kb") or {}).get("state") == "published":
            break
        time.sleep(0.25)
    yield
    for p in procs:
        p.terminate()


def login(employee_id, last):
    r = httpx.post(f"{API}/api/auth/login", json={"employee_id": employee_id, "last_name": last})
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["tech_id"]


def ask(h, q, site_id=None):
    return httpx.post(f"{API}/api/assistant", headers=h, json={"message": q, "site_id": site_id}, timeout=30).json()


SALEM = "S00101001"


def test_kb_published_and_scoped(stack):
    titles = list(httpx.get(f"{AOM}/test/state").json()["docs"].values())
    assert any(t.startswith("Field Maintenance Runbook") for t in titles)
    assert any(SALEM in t for t in titles)
    h, _ = login("204817", "Chen")
    a = ask(h, "What needs doing at this site today?", SALEM)
    assert a["context"]["kb_mode"] == "aom" and a["governed"]
    searched = [c[1] for c in httpx.get(f"{AOM}/test/state").json()["calls"] if c[0] == "kb_search"]
    assert all(d is not None for d in searched), "every KB search must be scoped to one document"


def test_llm_cache_shared_for_runbook_only(stack):
    h1, _ = login("204817", "Chen")
    h2, _ = login("318552", "Walker")
    a = ask(h1, "How does a budget override work?")
    b = ask(h2, "How does a budget override work?")
    assert a["personal"] is False and b["llm"]["status"] == "hit_exact"
    p1 = ask(h1, "How much budget is left at this site?", SALEM)
    p2 = ask(h2, "How much budget is left at this site?", "S00102001")
    assert p1["llm"]["namespace"] == "rag:telco-field-assistant:site" and p2["llm"]["status"] == "miss"


def test_rag_application_registered_and_scoped_to_runbook(stack):
    st = httpx.get(f"{AOM}/test/state").json()
    app = st["rag_apps"]["telco-field-assistant"]
    runbook = [d for d, t in st["docs"].items() if t.startswith("Field Maintenance Runbook")]
    assert app["enabled"] and app["document_ids"] == runbook
    assert set(app["allowed_roles"]) == {"field_technician", "admin"}

    h, _ = login("427190", "Alvarez")
    q = "What are the rules for climbing a tower?"
    a, b = ask(h, q), ask(h, q)
    assert a["context"]["source"] == "aom-rag" and a["llm"]["rag_app"] == "telco-field-assistant"
    assert b["context"]["status"] == "hit" and b["llm"]["status"] == "hit_exact"
    assert "climb" in a["reply"].lower() and a["sources"]
    rag = [c for c in httpx.get(f"{AOM}/test/state").json()["calls"] if c[0] == "rag_query"]
    # Runbook answers never retrieve a site's profile.
    assert rag and all(set(c[3]) <= set(runbook) for c in rag)


def test_site_context_cached_in_aom(stack):
    h, _ = login("204817", "Chen")
    q = "What was done last time at this site and how often is it worked on?"
    first, second = ask(h, q, "S00101003"), ask(h, q, "S00101003")
    assert second["context"]["status"] == "hit" and second["context"]["source"] == "aom"
    calls = httpx.get(f"{AOM}/test/state").json()["calls"]
    sets = [c for c in calls if c[0] == "ctx_set" and c[2].startswith("S00101003:history:")]
    assert sets and sets[0][1] == "rag:telco-field-assistant:site-context" and sets[0][3] is not None
    assert first["context"]["status"] in ("miss", "hit")


def test_budget_override_waits_for_human(stack):
    h, rid = login("204817", "Chen")
    oid = f"wo::{rid}::{uuid.uuid4().hex[:8]}"
    httpx.post(f"{API}/api/sync/push", headers=h, json={"docs": [{"collection": "work_orders", "id": oid, "doc": {
        "type": "request", "tech_id": rid, "site_id": SALEM, "tool": "request_budget_override",
        "args": {"site_id": SALEM, "lines": [{"sku": "FS-PWR-2204", "qty": 4}, {"sku": "FS-CLG-3101", "qty": 1},
                                                 {"sku": "FS-ANT-5101", "qty": 1}, {"sku": "FS-PWR-2310", "qty": 1}],
                 "reason": "Battery string failing on a critical site"}, "created_at": "2026-11-13T15:00:00Z"}}]})

    def req():
        docs = httpx.get(f"{API}/api/sync/pull", headers=h).json()["docs"]
        return next(d["doc"] for d in docs if d["id"] == oid)

    for _ in range(30):
        if req()["status"] == "awaiting_approval":
            break
        time.sleep(0.2)
    doc = req()
    assert doc["status"] == "awaiting_approval" and doc["governed"]
    httpx.post(f"{AOM}/test/approve/{doc['approval_id']}")
    for _ in range(30):
        if req()["status"] in ("completed", "parts_pending"):
            break
        time.sleep(0.2)
    assert req()["status"] in ("completed", "parts_pending")
    assert req()["item"]["budget_override"] is True
