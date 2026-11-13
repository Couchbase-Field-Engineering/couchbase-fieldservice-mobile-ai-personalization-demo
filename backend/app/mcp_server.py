"""`telco-field-service` - the MCP server registered with AOM.

Streamable HTTP at /fs/mcp/. AOM ingests these tool definitions into its
vetted catalog (embeddings for discovery, RBAC per role, drift detection)
and is the only caller the demo expects: the app and assistant reach these
tools through `POST /v1/tools/invoke`, never directly.

Business errors (over budget, access hold, unknown part, bad work type) come
back as `{"ok": false, ...}` results rather than MCP errors, so AOM records a
completed call and the technician gets a useful message instead of a gateway
failure.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import actions

log = logging.getLogger("fs.mcp")

mcp = FastMCP(
    "telco-field-service",
    instructions=("Telecom field service for a technician's network sites: preventive and corrective work plans from the "
                  "asset-health model, open alarms, spare parts and depot stock, work-order close-out, budget overrides, "
                  "outage windows, recurring tasks, RMAs and visit logs."),
    stateless_http=True,
    # Called by AOM over the Docker host gateway, so the Host header is not
    # localhost; same reasoning as AOM's own bundled sample servers.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


async def _run(fn, **kw) -> dict:
    try:
        res = await fn(**kw)
    except actions.ToolError as exc:
        return {"ok": False, "status": "failed", "summary": str(exc)}
    return res if isinstance(res, dict) and "ok" in res else {"ok": True, "status": "ok", "data": res}


@mcp.tool()
async def get_site_context(tech_id: str, site_id: str) -> dict:
    """Read a network site: type, contacts, SLA class, open alarms, asset health, maintenance budget and access hold, access notes, last work order, visit cadence and outage risk."""
    return await _run(actions.get_site_context, tech_id=tech_id, site_id=site_id)


@mcp.tool()
async def get_work_plan(tech_id: str, site_id: str) -> dict:
    """The asset-health model's work plan for a site: corrective tasks from open alarms, the preventive checklist, and recommended parts with days-to-failure, on-hand units at the serving depot and a budget check."""
    return await _run(actions.get_work_plan, tech_id=tech_id, site_id=site_id)


@mcp.tool()
async def search_parts(tech_id: str, site_id: str, query: str = "", category: str = "") -> dict:
    """Search the spare-parts catalog for a site: unit cost, depot on-hand units, swap time, whether the swap is service-affecting and when the part was last replaced here. category is one of power, cooling, radio, antenna, transport, fiber, site, tools."""
    return await _run(actions.search_parts, tech_id=tech_id, site_id=site_id, query=query, category=category)


@mcp.tool()
async def quote_work_order(tech_id: str, site_id: str, lines: list) -> dict:
    """Cost a set of part lines [{sku, qty}] for a site: parts total, swap minutes, service impact, budget check and any short depot stock."""
    return await _run(actions.quote_work_order, tech_id=tech_id, site_id=site_id, lines=lines)


@mcp.tool()
async def submit_work_order(tech_id: str, site_id: str, lines: list, ticket: str = "", work_type: str = "",
                            notes: str = "", tasks_done: list | None = None) -> dict:
    """Close out a work order for a site with part lines [{sku, qty}] and the checklist tasks completed. Issues depot stock (puts the rest on order), commits the cost to the site budget and clears alarms for the parts fitted. Fails with reason_code budget_limit when it exceeds the remaining budget, or site_hold when the site is on an access hold."""
    return await _run(actions.submit_work_order, tech_id=tech_id, site_id=site_id, lines=lines, ticket=ticket,
                      work_type=work_type, notes=notes, tasks_done=tasks_done)


@mcp.tool()
async def request_budget_override(tech_id: str, site_id: str, lines: list, reason: str, ticket: str = "",
                                  work_type: str = "", notes: str = "", tasks_done: list | None = None) -> dict:
    """Close out a work order above the site's remaining maintenance budget. Requires a reason; held for Field Ops approval. Once approved, the shortfall becomes a one-time extension and the work order is closed."""
    return await _run(actions.request_budget_override, tech_id=tech_id, site_id=site_id, lines=lines, reason=reason,
                      ticket=ticket, work_type=work_type, notes=notes, tasks_done=tasks_done)


@mcp.tool()
async def set_recurring_task(tech_id: str, site_id: str, sku: str, qty: int, cadence_weeks: int = 12) -> dict:
    """Create or replace a recurring replacement of a wear item at a site every 2, 4, 8, 12, 26 or 52 weeks."""
    return await _run(actions.set_recurring_task, tech_id=tech_id, site_id=site_id, sku=sku, qty=qty, cadence_weeks=cadence_weeks)


@mcp.tool()
async def create_rma(tech_id: str, site_id: str, work_order_id: str, sku: str, qty: int, reason: str) -> dict:
    """Create an RMA for a part on a recent work order (within 30 days): credits the cost back to the site budget and sets a depot return date."""
    return await _run(actions.create_rma, tech_id=tech_id, site_id=site_id, work_order_id=work_order_id, sku=sku, qty=qty, reason=reason)


@mcp.tool()
async def log_site_visit(tech_id: str, site_id: str, outcome: str, notes: str = "", next_visit_days: int = 0) -> dict:
    """Log a site visit (outcome: work_completed, no_fault_found, follow_up, no_access), mark the route stop visited and schedule the next visit."""
    return await _run(actions.log_site_visit, tech_id=tech_id, site_id=site_id, outcome=outcome, notes=notes,
                      next_visit_days=next_visit_days)


@mcp.tool()
async def request_outage_window(tech_id: str, site_id: str, duration_min: int, reason: str) -> dict:
    """Request a planned service-affecting outage window (5 to 240 minutes) at a site. Requires a reason; held for NOC approval."""
    return await _run(actions.request_outage_window, tech_id=tech_id, site_id=site_id, duration_min=duration_min, reason=reason)
