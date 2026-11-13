"""Sync Gateway admin calls: one SG user per field tech, and session minting.

The tech signs in to this backend (employee id + last name); the backend makes
sure an SG user named after the tech_id exists with exactly three channels -
`tech:<tech_id>`, `area:<area_id>` and `catalog` - and mints a
session. The phone hands that session to Couchbase Lite's SessionAuthenticator,
the same way mobile_field_service does, so a tech's replicator can only ever
pull their own route, their area's sites and the catalog.
"""
from __future__ import annotations

import logging
import secrets

import httpx

from . import config
from .docs import CATALOG_CHANNEL, tech_channel, area_channel

log = logging.getLogger("fs.sgw")


def enabled() -> bool:
    return bool(config.SG_ADMIN_URL)


async def mint_session(tech_id: str, area_id: str) -> dict | None:
    if not enabled():
        return None
    auth = (config.SG_ADMIN_USERNAME, config.SG_ADMIN_PASSWORD)
    base = f"{config.SG_ADMIN_URL}/{config.SG_DB}"
    async with httpx.AsyncClient(timeout=10, auth=auth) as c:
        user = {"name": tech_id, "password": secrets.token_urlsafe(24)}
        # Collection-scoped channel grants (SG 3.x named collections).
        user["collection_access"] = {
            config.COUCHBASE_SCOPE: {col: {"admin_channels": [tech_channel(tech_id), area_channel(area_id), CATALOG_CHANNEL]}
                                     for col in ("sites", "techs", "work_plans", "work_orders", "assistant",
                                                 "context_cache", "catalog")}}
        r = await c.put(f"{base}/_user/{tech_id}", json=user)
        if r.status_code >= 400:
            log.warning("SG user upsert failed: %s %s", r.status_code, r.text[:200])
            return None
        r = await c.post(f"{base}/_session", json={"name": tech_id, "ttl": config.SG_SESSION_TTL_SECONDS})
        if r.status_code >= 400:
            log.warning("SG session failed: %s %s", r.status_code, r.text[:200])
            return None
        s = r.json()
        return {"session_id": s.get("session_id"), "cookie_name": s.get("cookie_name", "SyncGatewaySession"),
                "expires": s.get("expires"), "db": config.SG_DB, "url": config.SG_PUBLIC_URL or None}
