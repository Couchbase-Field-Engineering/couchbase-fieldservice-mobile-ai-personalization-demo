"""One way to run a field-service tool.

With AOM configured, every tool call - whether it came from a tap in the app
(an offline-first `work_orders` document) or from the assistant - goes through
`POST /v1/tools/invoke` as `telco-field-service::<tool>`. AOM re-checks RBAC and
the agent's tool scope, may park the call for a human (budget overrides,
outage windows), traces it, audits it, scans the response, then calls this
backend's MCP server, which runs the action in actions.py.

Without AOM (STORE_DRIVER=memory quick start, or AOM down) the same action
runs in-process and the result says `governed: false`.
"""
from __future__ import annotations

import logging

from . import actions, config
from .aom_client import AOMError, PendingApproval, aom

log = logging.getLogger("fs.tools")


def tool_id(name: str) -> str:
    return f"{config.AOM_MCP_SERVER_ID}::{name}"


async def run_local(name: str, args: dict) -> dict:
    fn = actions.TOOLS.get(name)
    if not fn:
        return {"ok": False, "status": "failed", "summary": f"Unknown tool '{name}'"}
    try:
        res = await fn(**args)
    except actions.ToolError as exc:
        return {"ok": False, "status": "failed", "summary": str(exc)}
    except TypeError as exc:
        return {"ok": False, "status": "failed", "summary": f"Bad arguments for {name}: {exc}"}
    if isinstance(res, dict) and "ok" not in res:
        res = {"ok": True, "status": "ok", "data": res}
    return res


async def invoke(name: str, args: dict, approval_id: str | None = None) -> dict:
    """Returns the tool result plus `governed`, `trace_id`, and - when AOM
    holds the call - status `awaiting_approval` with `approval_id`."""
    if aom.enabled:
        try:
            resp = await aom.invoke(tool_id(name), args, approval_id=approval_id)
            result = resp.get("result") or {}
            if isinstance(result, dict) and "ok" not in result:
                result = {"ok": True, "status": "ok", "data": result}
            result.update({"governed": True, "trace_id": (resp.get("trace") or {}).get("trace_id"),
                           "aom_latency_ms": resp.get("latency_ms"),
                           "hijack_warning": bool(resp.get("hijack_warning"))})
            return result
        except PendingApproval as pa:
            return {"ok": True, "status": "awaiting_approval", "governed": True,
                    "approval_id": pa.approval.get("approval_id"), "trace_id": pa.trace_id,
                    "summary": "This needs an approval (Field Ops for budget, the NOC for outage windows) before it's applied. "
                               "The card will update as soon as they decide."}
        except AOMError as exc:
            if exc.status in (400, 403, 404, 422, 429, 502):
                # AOM answered and refused, or the tool itself failed downstream.
                msg = _detail(exc.body) or str(exc)
                if exc.status == 502 and "Downstream MCP call failed:" in msg:
                    msg = msg.split("Downstream MCP call failed:", 1)[1].strip()
                return {"ok": False, "status": "failed", "governed": True, "summary": msg, "aom_status": exc.status}
            log.warning("AOM unavailable for %s - running locally: %s", name, exc)
    res = await run_local(name, args)
    res["governed"] = False
    return res


async def approval_status(approval_id: str) -> str | None:
    if not aom.enabled:
        return None
    try:
        data = await aom.get_approval(approval_id)
        return (data.get("approval") or {}).get("status")
    except AOMError:
        return None


def _detail(body) -> str | None:
    import json
    try:
        d = json.loads(body or "{}").get("detail")
        return d if isinstance(d, str) else json.dumps(d)
    except Exception:  # noqa: BLE001
        return None
