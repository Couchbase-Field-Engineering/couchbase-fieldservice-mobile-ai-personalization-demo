"""Document ids, channel names and small shared helpers."""
from __future__ import annotations

import datetime as dt

from . import config

STATE = {"export_date": None}  # set by the loader


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> dt.date:
    """The demo's notion of 'today' - see config.DEMO_TODAY."""
    if config.DEMO_TODAY:
        return dt.date.fromisoformat(config.DEMO_TODAY)
    if STATE.get("export_date"):
        return dt.date.fromisoformat(STATE["export_date"])
    return dt.date.today()


# Channels. A tech's Sync Gateway user gets exactly three: their own channel
# (route, work orders, assistant chat), their area's channel (every site
# and work plan in the area) and the shared catalog.
def tech_channel(tech_id: str) -> str:
    return f"tech:{tech_id}"


def area_channel(area_id: str) -> str:
    return f"area:{area_id}"


CATALOG_CHANNEL = "catalog"


def tech_id_doc(r):
    return f"tech::{r}"


def site_id_doc(a):
    return f"site::{a}"


def plan_id(a):
    return f"plan::{a}"


def chat_id(r):
    return f"chat::{r}"


def ctx_id(scope, intent):
    """scope = site id for site context, tech id for runbook context."""
    return f"ctx::{scope}::{intent}"


def inventory_id(depot):
    return f"inv::{depot}"


CATALOG_ID = "catalog::v1"


def days_since(date_str: str | None) -> int | None:
    if not date_str:
        return None
    return (today() - dt.date.fromisoformat(date_str[:10])).days


def days_until(date_str: str | None) -> int | None:
    if not date_str:
        return None
    return (dt.date.fromisoformat(date_str[:10]) - today()).days


def money(x: float) -> str:
    return f"${x:,.2f}"
