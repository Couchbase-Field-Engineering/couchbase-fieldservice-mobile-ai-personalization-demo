"""Processes offline-first work orders and other field actions.

The phone never calls a work-order API directly. A tap writes a `work_orders`
document into Couchbase Lite (`status: "pending"`); the replicator pushes it
through Sync Gateway whenever the tech has connectivity, and this worker picks
it up from Couchbase, runs it through AOM (tool_gateway), and writes the
outcome back onto the same document. Sync Gateway replicates the update to
the phone, where a live query flips the card from "On device" to "Completed".
Budget overrides and outage windows sit in `awaiting_approval` until a
person decides in AOM's Approvals page; this worker polls and re-invokes with
the approval id.
"""
from __future__ import annotations

import asyncio
import logging

from . import config, metrics, tool_gateway
from .actions import READ_ONLY_TOOLS, TOOLS
from .docs import now_iso, tech_channel
from .store import store

log = logging.getLogger("fs.worker")

# Tools a tech's phone may request. Read-only tools are answered by the
# assistant; nothing here lets a phone act as another tech.
REQUESTABLE = set(TOOLS) - set(READ_ONLY_TOOLS)


async def process(key: str, doc: dict) -> dict:
    first = doc.get("status") != "awaiting_approval"
    tech_id = doc.get("tech_id")
    tool = doc.get("tool")
    if doc.get("status") == "awaiting_approval":
        status = await tool_gateway.approval_status(doc.get("approval_id", ""))
        if status in (None, "pending"):
            return doc
        if status != "approved":
            doc.update(status="failed", summary=f"This request was not approved ({status}).",
                       completed_at=now_iso())
            await store.upsert("work_orders", key, doc)
            return doc
        result = await tool_gateway.invoke(tool, {**doc.get("args", {}), "tech_id": tech_id},
                                           approval_id=doc["approval_id"])
    else:
        if tool not in REQUESTABLE:
            doc.update(status="failed", summary=f"'{tool}' can't be requested from the app", completed_at=now_iso())
            await store.upsert("work_orders", key, doc)
            return doc
        doc.update(status="processing", processing_at=now_iso())
        await store.upsert("work_orders", key, doc)
        # tech_id comes from the document, which Sync Gateway only accepted
        # from that signed-in tech (requireUser in the sync function).
        args = {k: v for k, v in (doc.get("args") or {}).items() if k != "tech_id"}
        result = await tool_gateway.invoke(tool, {**args, "tech_id": tech_id})

    status = result.get("status", "failed")
    if result.get("ok") and status in ("ok", "completed", "parts_pending"):
        status = "completed" if status == "ok" else status
    if not result.get("ok"):
        status = "failed"
    doc.update({
        "status": status, "summary": result.get("summary"), "cost_usd": result.get("cost_usd"),
        "item": result.get("item"), "reason_code": result.get("reason_code"), "auth": result.get("auth"),
        "governed": result.get("governed", False), "trace_id": result.get("trace_id"),
        "approval_id": result.get("approval_id", doc.get("approval_id")),
        "completed_at": None if status == "awaiting_approval" else now_iso(),
        "channels": [tech_channel(tech_id)],
    })
    await store.upsert("work_orders", key, doc)
    metrics.order(doc, first)
    log.info("work order %s %s -> %s", key, tool, status)
    return doc


async def run_once() -> int:
    rows = await store.pending_work_orders()
    for key, doc in rows:
        try:
            await process(key, doc)
        except Exception as exc:  # noqa: BLE001
            log.exception("work order %s failed", key)
            doc.update(status="failed", summary=f"Something went wrong: {exc}", completed_at=now_iso())
            await store.upsert("work_orders", key, doc)
    return len(rows)


async def loop():
    while True:
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001
            log.warning("worker tick failed: %s", exc)
        await asyncio.sleep(config.REQUEST_POLL_SECONDS)
