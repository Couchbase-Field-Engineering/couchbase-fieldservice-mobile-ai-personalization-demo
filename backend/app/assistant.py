"""Telecom Field Service Assistant - the agent behind the app's Assistant tab.

One turn:

1. **Classify** the question into an intent, and decide whether it is about
   *this site* (needs the site's data) or a *runbook* question anyone could
   ask ("how does a budget override work?", "how do I test a battery string?").
2. **Runbook questions -> AOM RAG Application.** One call to
   `/v1/agent/rag/telco-field-assistant/query`. The app is scoped to today's
   Field Maintenance Runbook document; AOM runs retrieval behind its Context
   Cache and generation behind its LLM Cache, and counts the query on its RAG
   Applications page. If the app isn't registered (or AOM predates RAG
   Applications) the question takes the site path below without site data.
3. **Site questions -> Context Caching.** Look the context up in AOM's
   Context Cache (`/v1/context/get`, namespace
   `rag:telco-field-assistant:site-context`), then in the Couchbase
   `ctx::<site>::<intent>` document. On a miss, assemble it: AOM Knowledge
   Base retrieval scoped to this site's profile document and to the runbook,
   plus live facts from the governed MCP tools (work plan, open alarms, depot
   on-hand, budget). It is stored in AOM (`/v1/context/set`, with the real
   build time) and in Couchbase, keyed by the export date and the site
   revision, so the next daily load or any work order on the site
   invalidates it. The Couchbase copy carries the area channel, so Sync
   Gateway puts it on the technician's phone too - which is what lets the
   app answer inside a shelter with no signal.
4. **Memory** - recall what technicians have noted about this site before
   (AOM agent memory), live every turn.
5. **LLM Caching** - complete through AOM `/v1/llm/complete` in the
   `rag:telco-field-assistant:site` namespace (the `rag:<app>:` prefix is
   how AOM attributes the activity to the RAG application).
6. Suggest one-tap actions; the app turns a tap into an offline-first
   `work_orders` document.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from . import catalog as C
from . import config, knowledge, metrics, rag_app, tool_gateway
from .aom_client import AOMError, aom, current_trace
from .docs import (STATE, site_id_doc, chat_id, ctx_id, days_since, money, now_iso, tech_channel, tech_id_doc,
                   area_channel)
from .store import store

log = logging.getLogger("fs.assistant")

INTENTS = ["workplan", "parts", "alarms", "outage", "access", "rma", "budget", "history", "recurring", "visit", "general"]
# Context-cache keys: site context per intent, plus a runbook-only
# context per intent for generic questions (no site data in it).
CONTEXT_KEYS = INTENTS + [f"runbook_{i}" for i in INTENTS]

KEYWORDS = {
    "budget": ["budget", "override", "over budget", "limit", "spend", "authoriz", "authoris", "hold", "approval", "committed"],
    "rma": ["rma", "return", "dead on arrival", "doa", "wrong part", "faulty part", "send back"],
    "recurring": ["recurring", "every week", "every month", "every quarter", "cadence", "interval", "replace every",
                  "schedule a", "on a schedule"],
    "outage": ["outage window", "window", "off-air", "off air", "downtime", "service affecting", "service-affecting", "noc",
               "take down", "lock the sector", "power down"],
    "parts": ["in stock", "stock", "available", "availability", "on hand", "backorder", "on order", "substitute", "part number",
              "sku", "how much", "cost", "price", "depot", "spare"],
    "access": ["access", "gate", "key", "escort", "landlord", "climb", "hours", "get in", "lockbox", "permit", "directions"],
    "alarms": ["alarm", "alarms", "fault", "vswr", "rectifier fail", "high temp", "temperature", "link down", "degraded",
               "health", "asset", "why is"],
    "history": ["history", "last work order", "last time", "previous", "replaced before", "usually", "how often",
                "what was done", "who was here"],
    "visit": ["visit", "stop", "route", "next time", "come back", "follow up", "log"],
    "workplan": ["work plan", "plan", "recommend", "what should", "what needs", "needs doing", "to do", "checklist",
                 "preventive", "corrective", "predict", "about to fail", "failing", "fail", "replace", "battery", "batteries",
                 "filter", "today", "job"],
}
SITE_RE = re.compile(r"\b(this|their|they|them|the site|this site|the tower|this tower|this cabinet|here|we|our|my)\b", re.I)
SITE_INTENTS = {"workplan", "alarms", "history", "visit"}

# Canonical retrieval query per intent: the cached context is per intent, so
# it is retrieved with a stable query rather than the wording of whichever
# question happened to miss the cache first.
INTENT_QUERY = {
    "workplan": "recommended parts days to failure preventive checklist corrective alarms work history",
    "parts": "spare parts cost depot on hand backorder substitute",
    "alarms": "open alarms asset health VSWR rectifier temperature link",
    "outage": "outage window service affecting NOC approval restore target",
    "access": "site access hours climb escort landlord access hold notes",
    "rma": "RMA return part dead on arrival credit depot",
    "budget": "maintenance budget committed budget override Field Ops approval access hold",
    "history": "work history maintenance spend last work order wear",
    "recurring": "recurring task replacement cadence wear item",
    "visit": "site visit cadence next visit notes route",
    "general": "frequently asked questions procedure policy",
}

PERSONA = ("You are the Telecom Field Service Assistant in a field technician's mobile app, helping them on site at a "
           "cell tower, exchange or fiber cabinet. Be direct, concise (under 120 words) and specific: part numbers, "
           "quantities, alarms, dates. Use only the facts in CONTEXT. Never invent stock, alarms or work orders. Put safety "
           "first: mention an outage window or climb rule when the work needs one. Never say a work order is closed - the "
           "technician confirms actions with the buttons shown under your reply.")


def classify(message: str) -> tuple[str, bool]:
    m = message.lower()
    scores = {i: sum(1 for k in kws if k in m) for i, kws in KEYWORDS.items()}
    intent = max(scores, key=scores.get)
    if scores[intent] == 0:
        intent = "general"
    about_site = bool(SITE_RE.search(message)) or intent in SITE_INTENTS
    if intent == "general" and not about_site:
        return "general", False
    # A procedure or policy question phrased generically ("how does a budget
    # override work?", "how do I test a battery string?") stays on the shared
    # runbook path even though its intent is site-capable.
    if not SITE_RE.search(message) and re.match(r"\s*(how|what is|what are|what's the|is|are|can|do|does|who|which|when do)\b", m):
        return intent, False
    return intent, True


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


async def kb_doc_id(key: str) -> str | None:
    doc = await store.get("lookups", f"kbdoc::{key}")
    return doc.get("document_id") if doc else None


# --------------------------------------------------------------------------
# Context cache
# --------------------------------------------------------------------------
async def invalidate_context(site_id: str):
    for key in INTENTS:
        await store.remove("context_cache", ctx_id(site_id, key))


async def _kb(query: str, document_id: str | None, top_k=3) -> tuple[list[dict], str]:
    if not (aom.enabled and document_id):
        return [], "unavailable"
    try:
        res = await aom.knowledge_search(query, top_k=top_k, document_id=document_id)
        return [{"title": r.get("document_title"), "content": r.get("content"), "score": round(r.get("score") or 0, 3),
                 "document_id": r.get("document_id"), "source": "aom-kb"} for r in res.get("results", [])], "aom"
    except AOMError as exc:
        log.warning("KB search failed: %s", exc)
        return [], "error"


def _local_profile_chunks(site: dict, intent: str) -> list[dict]:
    md = knowledge.site_profile_markdown(site)
    sections = md.split("\n## ")
    want = {"workplan": ["Asset health", "Alarms"], "parts": ["Work history", "Asset health"], "alarms": ["Alarms", "Asset health"],
            "outage": ["SLA", "Alarms"], "access": ["Site", "Visit"], "rma": ["Work history"], "budget": ["SLA", "Work history"],
            "history": ["Work history", "Visit"], "recurring": ["Work history"], "visit": ["Visit", "Site"],
            "general": ["Site"]}[intent]
    out = []
    for s in sections:
        if any(s.startswith(w) for w in want):
            out.append({"title": f"Site profile {site['site_id']}", "content": s[:1200], "score": None,
                        "document_id": None, "source": "local-dump"})
    return out


def _local_runbook_chunks(query: str) -> list[dict]:
    q = query.lower()
    scored = []
    for f in knowledge.FAQ:
        s = sum(1 for k in f["keywords"] if k in q)
        if s:
            scored.append((s, f))
    scored.sort(key=lambda x: -x[0])
    return [{"title": "Field Maintenance Runbook", "content": f"{f['q']} {f['a']}", "answer": f["a"], "score": None,
             "document_id": None, "source": "local-runbook"} for _, f in scored[:3]]


async def _facts(tech_id: str, site_id: str, intent: str, message: str) -> dict:
    if intent in ("workplan", "parts", "alarms", "outage", "recurring"):
        tool, args = "get_work_plan", {}
    else:
        tool, args = "get_site_context", {}
    res = await tool_gateway.invoke(tool, {"tech_id": tech_id, "site_id": site_id, **args})
    data = res.get("data", res)
    facts = {"tool": tool, "governed": res.get("governed", False), "trace_id": res.get("trace_id"), "data": data}
    if intent == "parts":
        # Also look the mentioned parts up in the catalog with this site's depot stock.
        stop = ("much", "does", "have", "they", "this", "what", "price", "stock", "cost", "site", "depot", "there", "here", "many")
        words = [w for w in re.findall(r"[a-z]{3,}", message.lower()) if w not in stop]
        if words:
            srch = await tool_gateway.invoke("search_parts", {"tech_id": tech_id, "site_id": site_id, "query": " ".join(words[:4])})
            facts["catalog"] = (srch.get("data", srch) or {}).get("items", [])[:5]
    return facts


def _aom_context_key(scope: str, cache_key: str, site: dict | None, personal: bool) -> str:
    """Key in AOM's Context Cache. The export date and (for site context)
    the site revision are part of the key, so a new daily export or any
    order makes the old entry unreachable at once. Runbook context holds no
    site data, so every tech shares one entry per intent."""
    if personal and site:
        return f"{scope}:{cache_key}:{site.get('export_date')}:r{site.get('rev', 0)}"
    return f"{cache_key}:{STATE.get('export_date')}"


def _local_valid(doc: dict | None, site: dict | None, personal: bool) -> bool:
    if not doc or doc.get("export_date") != STATE.get("export_date"):
        return False
    return not personal or (site is not None and doc.get("site_rev") == site.get("rev", 0))


async def get_context(tech_id: str, intent: str, site: dict | None, personal: bool, message: str = "") -> dict:
    """Context Caching, with AOM's Context Cache in front of the assembly.

    1. AOM `/v1/context/get` in the `rag:<app>:site-context` namespace, so
       hit rate and latency avoided show on AOM's Context Cache and RAG
       Applications pages.
    2. On a miss (or with AOM unreachable), the Couchbase `context_cache`
       document, if it was built from today's export and the current site.
    3. Otherwise assemble: KB retrieval scoped to this site's profile
       document and the runbook, plus live facts from the governed MCP
       tools. The result goes to AOM (`/v1/context/set` with the real build
       time as `source_latency_ms`) and to Couchbase, where the area
       channel puts it on the tech's phone for offline answers.
    """
    personal = personal and site is not None
    cache_key = intent if personal else f"runbook_{intent}"
    scope = site["site_id"] if personal else tech_id
    key = ctx_id(scope, cache_key)
    channels = [area_channel(site["area_id"])] if personal else [tech_channel(tech_id)]
    aom_key = _aom_context_key(scope, cache_key, site, personal)
    t0 = time.perf_counter()
    aom_status = "off"
    if aom.enabled:
        try:
            res = await aom.context_get(aom_key, config.CONTEXT_NAMESPACE)
            aom_status = (res.get("cache") or {}).get("status") or ("hit" if res.get("hit") else "miss")
            value = res.get("value")
            if res.get("hit") and isinstance(value, dict):
                # A shared runbook entry may have been stored by another tech's
                # turn: re-home it before it syncs to this tech's phone.
                doc = dict(value, scope=scope, channels=channels)
                local = await store.get("context_cache", key)
                if not _local_valid(local, site, personal):
                    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
                doc["_cache"] = {"status": "hit", "source": "aom", "namespace": config.CONTEXT_NAMESPACE,
                                 "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
                return doc
        except AOMError as exc:
            aom_status = "error"
            log.info("AOM context get failed: %s", exc)

    cached = await store.get("context_cache", key)
    if _local_valid(cached, site, personal):
        cached["_cache"] = {"status": "hit", "source": "couchbase", "aom": aom_status,
                            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if aom_status == "miss":
            await _aom_context_set(aom_key, cached, cached.get("build_ms"))
        return cached

    query = INTENT_QUERY[intent]
    site_doc = await kb_doc_id(site["site_id"]) if personal else None
    runbook_doc = await kb_doc_id("runbook")
    kb_profile, kb_mode = ([], "skipped")
    if personal and intent != "general":
        kb_profile, kb_mode = await _kb(query, site_doc)
        if not kb_profile:
            kb_profile = _local_profile_chunks(site, intent)
    kb_runbook, pb_mode = await _kb(query, runbook_doc)
    if not kb_runbook:
        kb_runbook = _local_runbook_chunks(query + " " + intent)
    if kb_mode == "skipped":
        kb_mode = pb_mode
    facts = await _facts(tech_id, site["site_id"], intent, message) if personal and intent != "general" else {}
    build_ms = round((time.perf_counter() - t0) * 1000, 1)
    doc = {
        "type": "context_cache", "scope": scope, "site_id": site["site_id"] if personal else None,
        "intent": intent, "personal": personal, "query": query,
        "export_date": STATE.get("export_date"), "site_rev": site.get("rev", 0) if personal else None,
        "built_at": now_iso(), "build_ms": build_ms, "kb_mode": kb_mode,
        "kb_profile": kb_profile, "kb_runbook": kb_runbook, "facts": facts,
        "site_document_id": site_doc, "runbook_document_id": runbook_doc,
        "aom_key": aom_key, "channels": channels,
    }
    await store.upsert("context_cache", key, doc, ttl=config.CONTEXT_CACHE_TTL_SECONDS)
    await _aom_context_set(aom_key, doc, build_ms)
    doc = dict(doc)
    doc["_cache"] = {"status": "miss", "source": "built", "aom": aom_status, "latency_ms": build_ms}
    return doc


async def _aom_context_set(aom_key: str, doc: dict, build_ms) -> None:
    if not aom.enabled:
        return
    value = {k: v for k, v in doc.items() if not k.startswith("_")}
    if not value.get("personal"):
        if value.get("kb_profile") or value.get("facts"):
            return  # never share site data across techs' runbook entries
        for k in ("scope", "channels", "site_document_id", "site_id"):
            value.pop(k, None)
    try:
        await aom.context_set(aom_key, value, config.CONTEXT_NAMESPACE, ttl_seconds=config.CONTEXT_CACHE_TTL_SECONDS,
                              source_latency_ms=int(build_ms or 0))
    except AOMError as exc:
        # 409 = context caching switched off in AOM's policy, 413 = over its size limit.
        log.info("AOM context set skipped: %s", exc)


# --------------------------------------------------------------------------
# Answer composition
# --------------------------------------------------------------------------
def _site_summary(a: dict) -> str:
    c = a["auth"]
    last = a["work_history"][0] if a.get("work_history") else None
    alarms = a.get("alarms", [])
    return (f"{a['site_name']} ({a.get('site_code')}, {a['site_type_name']}, {a['address']['city']}, {a['address']['state']}), "
            f"{a['sla']['tier_name']} SLA class, restore target {a['sla'].get('restore_hours')}h. "
            + (f"{len(alarms)} open alarm(s): " + "; ".join(f"{al['severity']} {al['text']}" for al in alarms[:3]) + ". " if alarms else "No open alarms. ")
            + f"Quarterly maintenance budget ${c['budget_limit_usd']:,.0f}, committed ${c['committed_usd']:,.2f}"
            + (f", ON ACCESS HOLD ({c.get('hold_reason')})" if c.get("on_hold") else "") + ". "
            + (f"Last work order {last['work_order_id']} on {last['date']} for ${last['total_usd']:,.2f}. " if last else "No recent work orders. ")
            + f"Spares from {C.DEPOTS[a['access']['depot']]['name']}; access {a['access'].get('access_hours')}"
            + ("; tower climb required" if a["access"].get("climb_required") else "") + ".")


def _facts_text(facts: dict) -> str:
    d = facts.get("data") or {}
    out = []
    if facts.get("tool") == "get_work_plan":
        rows = [f"{l['qty']} x {l['name']} ({l['sku']}) at ${l['unit_cost']} = ${l['line_total']}, depot on hand {l['on_hand_at_depot']}"
                + (f", predicted failure in {l['days_to_failure']}d" if l.get("days_to_failure") is not None else "")
                + (", service-affecting" if l.get("service_affecting") else "")
                for l in d.get("lines", [])]
        if rows:
            out.append("Recommended parts: " + "; ".join(rows))
        tasks = d.get("tasks") or []
        cm = [t["title"] for t in tasks if t.get("kind") == "corrective"]
        pm = [t["title"] for t in tasks if t.get("kind") == "preventive"]
        if cm:
            out.append("Corrective tasks: " + "; ".join(cm))
        if pm:
            out.append("Preventive checklist: " + "; ".join(pm))
        t = d.get("totals") or {}
        if t:
            out.append(f"Plan parts total ${t.get('total_usd')}, about {t.get('swap_minutes')} min of swaps"
                       + (", includes service-affecting work" if t.get("service_affecting") else ""))
        cr = d.get("auth") or {}
        if cr:
            out.append(f"Budget: ${cr.get('available_usd')} available of ${cr.get('budget_limit_usd')}"
                       + (f", shortfall ${cr.get('shortfall_usd')}" if cr.get("shortfall_usd") else "")
                       + (", ON ACCESS HOLD" if cr.get("on_hold") else ""))
    elif d:
        cr = d.get("auth") or {}
        out.append(f"Budget available ${cr.get('available_usd')} of ${cr.get('budget_limit_usd')}"
                   + (f", ON ACCESS HOLD {cr.get('hold_days')} days: {cr.get('hold_reason')}" if cr.get("on_hold") else ""))
        if d.get("last_work_order"):
            lo = d["last_work_order"]
            out.append(f"Last work order {lo['work_order_id']} {lo['date']} ${lo['total_usd']} ({lo.get('work_type')}, "
                       f"{len(lo.get('lines', []))} parts" + (", parts on order" if lo.get("backordered") else "") + ")")
        if d.get("recurring_tasks"):
            out.append("Recurring tasks: " + "; ".join(f"{s['qty']} x {s['name'].split(',')[0]} every {s['cadence_weeks']}w" for s in d["recurring_tasks"]))
        if d.get("visit"):
            v = d["visit"]
            out.append(f"Visits: last {v.get('last_visit')}, next {v.get('next_visit_date')}, every {v.get('cadence_days')} days")
        if d.get("access"):
            ac = d["access"]
            out.append(f"Access: {ac.get('access_hours')}; {ac.get('notes') or 'no notes'}"
                       + ("; tower climb required" if ac.get("climb_required") else ""))
    for it in facts.get("catalog") or []:
        out.append(f"Catalog: {it['name']} ({it['sku']}) ${it['unit_cost']}, depot on hand {it['on_hand_at_depot']}")
    return "\n".join(out)


def build_prompt(message: str, personal: bool, ctx: dict, site: dict | None, memories: list[str]) -> str:
    parts = [PERSONA, "", "CONTEXT:"]
    if personal and site:
        parts.append("Site: " + _site_summary(site))
        for c in ctx.get("kb_profile", [])[:3]:
            parts.append("Profile note: " + (c.get("content") or "")[:900])
        ft = _facts_text(ctx.get("facts") or {})
        if ft:
            parts.append(ft)
        for m in memories[:3]:
            parts.append("Earlier a technician noted: " + m[:300])
    for c in ctx.get("kb_runbook", [])[:3]:
        parts.append("Runbook: " + (c.get("content") or "")[:900])
    parts += ["", f"TECHNICIAN QUESTION: {message.strip()}", "", "ANSWER:"]
    return "\n".join(parts)


def compose_fallback(intent: str, personal: bool, message: str, ctx: dict, site: dict | None) -> str:
    """Deterministic answer from the same context - used when AOM has no LLM
    provider key (it returns a labelled stub) or AOM is not configured."""
    d = (ctx.get("facts") or {}).get("data") or {}
    if not personal or not site or intent == "general":
        pb = _local_runbook_chunks(message) or ctx.get("kb_runbook")
        if pb:
            return pb[0].get("answer") or pb[0]["content"]
        return ("I can help with the work plan, open alarms, parts and depot stock, outage windows, access, RMAs, budget and "
                "visit notes for the site you have open.")
    name = site["site_name"]
    depot = C.DEPOTS[site["access"]["depot"]]["name"]
    if intent in ("workplan", "recurring"):
        lines = d.get("lines", [])
        tasks = d.get("tasks", [])
        cm = [t for t in tasks if t.get("kind") == "corrective"]
        pm = [t for t in tasks if t.get("kind") == "preventive"]
        if not lines and not cm:
            return (f"Nothing is predicted to fail at {name} and there are no open alarms - run the {len(pm)}-step preventive "
                    "checklist and log the visit.")
        urgent = [l for l in lines if l.get("days_to_failure") is not None and l["days_to_failure"] <= 7]
        short = [l for l in lines if l["on_hand_at_depot"] < l["qty"]]
        t = d.get("totals") or {}
        txt = f"{d.get('work_type', 'Maintenance')} at {name}: "
        if cm:
            txt += f"{len(cm)} corrective task{'s' if len(cm) > 1 else ''} first ({cm[0]['title'][0].lower() + cm[0]['title'][1:]}), then "
        txt += f"the {len(pm)}-step checklist."
        if lines:
            txt += f" The model recommends {len(lines)} part line{'s' if len(lines) > 1 else ''}, {money(t.get('total_usd', 0))}."
        if urgent:
            txt += " Start with " + ", ".join(f"{l['name'].split(',')[0]} x{l['qty']} (failure predicted in ~{max(0, l['days_to_failure'])}d)" for l in urgent[:2]) + "."
        if short:
            txt += " Heads up: " + ", ".join(f"only {l['on_hand_at_depot']} {l['name'].split(',')[0]} at the depot" for l in short[:2]) + "."
        cr = d.get("auth") or {}
        if cr.get("on_hold"):
            txt += f" The site is on an access hold ({cr.get('hold_reason')}) - no work can be booked until it is released."
        elif cr and not cr.get("ok"):
            txt += (f" That is {money(cr.get('shortfall_usd', 0))} over the site's remaining budget - submit it as a budget "
                    "override and Field Ops will approve it.")
        if t.get("service_affecting"):
            txt += " Some of it is service-affecting: get an outage window from the NOC first."
        if intent == "recurring" and lines:
            top = next((l for l in lines if C.PRODUCT_BY_SKU[l["sku"]]["wear_item"]), lines[0])
            txt += (f" {top['name'].split(',')[0]} is a regular wear item here - a recurring replacement every 12 weeks "
                    "would keep it off the recommendation list.")
        return txt
    if intent == "alarms":
        alarms = d.get("alarms", [])
        if not alarms:
            return f"{name} has no open alarms as of this morning's export."
        return (f"{name} has {len(alarms)} open alarm{'s' if len(alarms) > 1 else ''}: "
                + "; ".join(f"{al['severity']} - {al['text']}" + (f" ({al['action']})" if al.get("action") else "") for al in alarms[:3]) + ".")
    if intent == "parts":
        items = (ctx.get("facts") or {}).get("catalog") or []
        if items:
            it = items[0]
            return (f"{it['name']} ({it['sku']}) is {money(it['unit_cost'])} per {it['uom']}; {it['on_hand_at_depot']} on hand at {depot}."
                    + (f" Last replaced here {it['last_replaced']}." if it.get("last_replaced") else "")
                    + (" Swapping it is service-affecting - get an outage window first." if it.get("service_affecting") else ""))
        lines = d.get("lines", [])
        if lines:
            return (f"Parts recommended for {name}, with stock at {depot}: "
                    + "; ".join(f"{l['qty']} x {l['name'].split(',')[0]} ({l['on_hand_at_depot']} on hand)" for l in lines[:4]) + ".")
        return f"{name} draws spares from {depot}. Open the work order to search the parts catalog with live depot stock."
    if intent == "outage":
        sa = [l for l in d.get("lines", []) if l.get("service_affecting")]
        mins = sum(l["swap_min"] * l["qty"] for l in sa)
        if sa:
            return (f"Yes - {', '.join(l['name'].split(',')[0] for l in sa[:3])} {'is' if len(sa) == 1 else 'are'} service-affecting, "
                    f"about {mins} minutes of work. Request an outage window from the NOC below before you start; {name} is a "
                    f"{site['sla']['tier_name']} site with a {site['sla'].get('restore_hours')}-hour restore target.")
        return (f"Nothing on today's plan for {name} is service-affecting, so no outage window is needed. If you find you "
                "have to break an RF path or pull a backhaul optic, request one first.")
    if intent == "budget":
        cr = d.get("auth") or {}
        if cr.get("on_hold"):
            return (f"{name} is on an access hold for {cr.get('hold_days')} days: {cr.get('hold_reason')}. No work order can be "
                    "booked and an override can't release a hold - log the visit as no access and the Site Access desk will follow up.")
        return (f"{name} has {money(cr.get('available_usd', 0))} left this quarter: a {money(cr.get('budget_limit_usd', 0))} "
                f"maintenance budget with {money(cr.get('committed_usd', 0))} committed. Parts above that need a budget "
                "override approved by Field Ops.")
    if intent == "access":
        ac = site["access"]
        cr = d.get("auth") or {}
        return (f"{name}: access {ac.get('access_hours')}"
                + (", tower climb required (two climb-certified techs and a rescue kit)" if ac.get("climb_required") else ", no climb required")
                + "." + (f" Note: {ac['notes']}." if ac.get("notes") else "")
                + f" Field note: {site['visit'].get('signal_note')}."
                + (f" The site is on an access hold: {cr.get('hold_reason')}." if cr.get("on_hold") else ""))
    if intent == "rma":
        lo = d.get("last_work_order")
        if lo:
            return (f"The last work order here, {lo['work_order_id']} ({lo['date']}), is within the 30-day window - pick the part "
                    "and quantity and I'll create the RMA; the cost goes back on the site budget and the part is due at the depot "
                    "in five business days.")
        return "Parts can be returned within 30 days of being issued; the cost is credited back to the site budget."
    if intent == "history":
        sp = d.get("maintenance") or {}
        lo = d.get("last_work_order")
        return (f"{name}: {money(sp.get('last_12mo_usd', 0))} of parts over {sp.get('work_orders_last_12mo', 0)} work orders in the "
                f"last 12 months, average {money(sp.get('avg_work_order_usd', 0))}."
                + (f" Last work order {lo['work_order_id']} on {lo['date']}: {str(lo.get('work_type', 'maintenance')).lower()}, "
                   f"{money(lo['total_usd'])}." if lo else ""))
    if intent == "visit":
        v = d.get("visit") or {}
        return (f"Last visit {v.get('last_visit')}; this site is on a {v.get('cadence_days')}-day cadence, next due {v.get('next_visit_date')}. "
                "Log this visit below and I'll schedule the next one.")
    return "Here's what I found for this site."


def suggest_actions(intent: str, ctx: dict, site: dict | None, message: str) -> list[dict]:
    if not site:
        return []
    d = (ctx.get("facts") or {}).get("data") or {}
    acts: list[dict] = []
    aid = site["site_id"]
    if intent in ("workplan", "parts", "alarms"):
        lines = d.get("lines", [])
        cr = d.get("auth") or {}
        if lines and not cr.get("on_hold"):
            payload = [{"sku": l["sku"], "qty": l["qty"]} for l in lines]
            t = d.get("totals") or {}
            base = {"site_id": aid, "lines": payload, "work_type": d.get("work_type") or ""}
            if cr and not cr.get("ok"):
                acts.append({"label": f"Submit as budget override · {money(t.get('total_usd', 0))}", "tool": "request_budget_override",
                             "args": {**base, "reason": f"Recommended parts exceed the remaining site budget by {money(cr.get('shortfall_usd', 0))}; "
                                                        "failure predicted within the SLA window"}})
            else:
                acts.append({"label": f"Close out recommended work · {money(t.get('total_usd', 0))}", "tool": "submit_work_order",
                             "args": base})
        if cr.get("on_hold"):
            acts.append({"label": "Log visit · no access", "tool": "log_site_visit",
                         "args": {"site_id": aid, "outcome": "no_access", "notes": "Access hold - could not start work"}})
        else:
            acts.append({"label": "Review in Work order", "screen": "workorder", "args": {"site_id": aid}})
    elif intent == "outage":
        sa = [l for l in d.get("lines", []) if l.get("service_affecting")]
        mins = max(15, min(240, sum(l["swap_min"] * l["qty"] for l in sa) or 30))
        acts.append({"label": f"Request {mins}-min outage window", "tool": "request_outage_window",
                     "args": {"site_id": aid, "duration_min": mins,
                              "reason": ("Service-affecting swap: " + ", ".join(l["name"].split(",")[0] for l in sa[:3])) if sa
                              else f"Service-affecting work requested on site: {message.strip()[:120]}"}})
    elif intent == "budget":
        cr = d.get("auth") or {}
        if cr.get("on_hold"):
            acts.append({"label": "Log visit · no access", "tool": "log_site_visit",
                         "args": {"site_id": aid, "outcome": "no_access", "notes": "Access hold - could not start work"}})
        else:
            acts.append({"label": "Open Work order", "screen": "workorder", "args": {"site_id": aid}})
    elif intent == "recurring":
        lines = [l for l in d.get("lines", []) if C.PRODUCT_BY_SKU.get(l["sku"], {}).get("wear_item")]
        if lines:
            top = lines[0]
            acts.append({"label": f"Recurring · {top['qty']} x {top['name'].split(',')[0]} / 12 wks", "tool": "set_recurring_task",
                         "args": {"site_id": aid, "sku": top["sku"], "qty": top["qty"], "cadence_weeks": 12}})
    elif intent == "rma":
        lo = d.get("last_work_order")
        if lo and lo.get("lines"):
            l0 = lo["lines"][0]
            acts.append({"label": f"RMA 1 x {l0['name'].split(',')[0]} from {lo['work_order_id']}", "tool": "create_rma",
                         "args": {"site_id": aid, "work_order_id": lo["work_order_id"], "sku": l0["sku"], "qty": 1,
                                  "reason": f"Technician-reported via assistant: {message.strip()[:120]}"}})
    elif intent == "visit":
        acts.append({"label": "Log visit · work completed", "tool": "log_site_visit", "args": {"site_id": aid, "outcome": "work_completed"}})
        acts.append({"label": "Log visit · follow up", "tool": "log_site_visit", "args": {"site_id": aid, "outcome": "follow_up"}})
    elif intent in ("history", "access"):
        acts.append({"label": "Open Work order", "screen": "workorder", "args": {"site_id": aid}})
    return acts


# Only durable things the technician notes about the site become memories
# ("the landlord wants a call before roof access", "the gate code changed").
# Plain questions don't, which also keeps repeat questions' prompts stable
# for the LLM cache.
STATEMENT_RE = re.compile(r"\b(they|they're|the landlord|the owner|customer|security|the guard|the gate|the key|the site|the generator)\s+"
                          r"(want|wants|prefer|prefers|said|asked|need|needs|is|are|was|has|have|changed|moved|leaks|trips)\b"
                          r"|\bnote that\b|\bremember\b", re.I)


async def _remember(site_id: str, tech_id: str, message: str, intent: str, session_id: str):
    if not aom.enabled or not STATEMENT_RE.search(message):
        return
    try:
        await aom.memory_add(site_id, f"Technician {tech_id} noted ({intent}): {message.strip()[:500]}", session_id=session_id,
                             metadata={"intent": intent, "app": "telco-field-mobile", "tech_id": tech_id})
    except AOMError as exc:
        log.info("memory add skipped: %s", exc)


async def _recall(site_id: str, message: str) -> list[str]:
    if not aom.enabled:
        return []
    try:
        res = await aom.memory_search(site_id, message, top_k=3)
        return [e.get("content", "") for e in res.get("entries", []) if e.get("content")]
    except AOMError:
        return []


async def _ask_rag_app(message: str, intent: str) -> dict | None:
    """Runbook questions go to the assistant's AOM RAG Application: one call
    that runs AOM's Context Cache (retrieval), the KB search scoped to today's
    runbook, and the LLM Cache, and is counted on the RAG Applications page."""
    if not rag_app.usable():
        return None
    l0 = time.perf_counter()
    try:
        res = await aom.rag_query(config.RAG_APP_ID, message)
    except AOMError as exc:
        rag_app.query_failed(exc)
        log.info("RAG app query failed, answering on the assistant's own path: %s", exc)
        return None
    ms = round((time.perf_counter() - l0) * 1000, 1)
    retrieval = res.get("retrieval") or {}
    llm_res = res.get("llm") or {}
    cache = llm_res.get("cache") or {}
    srcs = res.get("sources") or []
    chunks = [{"title": c.get("document_title"), "content": c.get("preview"), "source": "aom-rag"} for c in srcs]
    reply = (res.get("answer") or "").strip()
    llm = {"status": cache.get("status", "skipped" if not res.get("llm") else "miss"), "similarity": cache.get("similarity"),
           "namespace": f"rag:{config.RAG_APP_ID}", "provider": llm_res.get("provider"), "model": llm_res.get("model"),
           "latency_ms": ms, "stub": bool(llm_res.get("stub")), "tokens_saved": llm_res.get("tokens_saved") or 0,
           "cost_saved_usd": llm_res.get("cost_saved_usd") or 0, "rag_app": config.RAG_APP_ID}
    if not res.get("llm") or llm["stub"] or not reply:
        reply = compose_fallback(intent, False, message, {"kb_runbook": chunks}, None)
        llm["composed_locally"] = True
    return {
        "reply": reply, "llm": llm,
        "sources": [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": "aom-rag"} for c in chunks[:3]],
        "context": {"status": retrieval.get("cache", "miss"), "latency_ms": retrieval.get("latency_ms", 0),
                    "source": "aom-rag", "rag_app": config.RAG_APP_ID, "chunks": retrieval.get("chunks"),
                    "export_date": STATE.get("export_date"), "kb_mode": "aom"},
        "trace_id": (res.get("trace") or {}).get("trace_id"),
    }


async def ask(tech_id: str, message: str, site_id: str | None = None, session_id: str | None = None) -> dict:
    session_id = session_id or f"app-{tech_id}"
    trace_id = uuid.uuid4().hex
    token = current_trace.set({"trace_id": trace_id, "session_id": session_id})
    t0 = time.perf_counter()
    try:
        tech = await store.get("techs", tech_id_doc(tech_id))
        if not tech:
            raise ValueError("unknown tech")
        site = None
        if site_id:
            site = await store.get("sites", site_id_doc(site_id))
            if not site or site.get("area_id") != tech.get("area_id"):
                raise ValueError("site not in this tech's area")
        intent, personal = classify(message)
        if personal and not site:
            result = {
                "reply": "Open a stop on your route first and I'll answer for that site - work plan, alarms, parts, "
                         "budget and history.", "intent": intent, "personal": True, "actions": [{"label": "Open today's route", "screen": "route"}],
                "sources": [], "context": {"status": "skipped", "latency_ms": 0}, "memory_recalled": 0,
                "llm": {"status": "skipped", "composed_locally": True}, "trace_id": None, "governed": False,
                "total_ms": round((time.perf_counter() - t0) * 1000, 1), "export_date": STATE.get("export_date"), "site_id": None,
            }
            await _append_chat(tech_id, message, result)
            return result
        if not personal:
            via_rag = await _ask_rag_app(message, intent)
            if via_rag:
                result = {
                    "reply": via_rag["reply"], "intent": intent, "personal": False, "actions": [],
                    "sources": via_rag["sources"], "context": via_rag["context"], "memory_recalled": 0,
                    "llm": via_rag["llm"], "trace_id": via_rag["trace_id"] or trace_id, "governed": True,
                    "total_ms": round((time.perf_counter() - t0) * 1000, 1), "export_date": STATE.get("export_date"),
                    "site_id": site_id,
                }
                metrics.assistant(result)
                await _append_chat(tech_id, message, result)
                return result
        ctx = await get_context(tech_id, intent, site, personal, message)
        memories = await _recall(site["site_id"], message) if personal and site else []
        prompt = build_prompt(message, personal, ctx, site, memories)
        namespace = config.LLM_NAMESPACE_SITE if personal else config.LLM_NAMESPACE_RUNBOOK
        llm = {"status": "local", "namespace": namespace, "provider": None, "model": None, "similarity": None,
               "latency_ms": None, "stub": False, "tokens_saved": 0}
        reply = None
        if aom.enabled:
            try:
                l0 = time.perf_counter()
                res = await aom.complete(prompt, namespace=namespace)
                cache = res.get("cache") or {}
                llm.update({"status": cache.get("status", "miss"), "similarity": cache.get("similarity"),
                            "provider": res.get("provider"), "model": res.get("model"),
                            "latency_ms": round((time.perf_counter() - l0) * 1000, 1), "stub": bool(res.get("stub")),
                            "tokens_saved": res.get("tokens_saved", 0), "cost_saved_usd": res.get("cost_saved_usd", 0)})
                if not res.get("stub") and (res.get("response") or "").strip():
                    reply = res["response"].strip()
            except AOMError as exc:
                llm["status"] = "error"
                llm["error"] = str(exc)[:200]
        if not reply:
            reply = compose_fallback(intent, personal, message, ctx, site)
            llm["composed_locally"] = True
        actions = suggest_actions(intent, ctx, site, message) if personal else []
        sources = ([{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                    for c in (ctx.get("kb_profile", []) if personal else [])[:2]]
                   + [{"title": c["title"], "snippet": (c.get("content") or "")[:160], "kind": c.get("source")}
                      for c in ctx.get("kb_runbook", [])[:2]])
        result = {
            "reply": reply, "intent": intent, "personal": personal, "actions": actions, "sources": sources,
            "context": {"status": ctx["_cache"]["status"], "latency_ms": ctx["_cache"]["latency_ms"],
                        "source": ctx["_cache"].get("source"),
                        "built_at": ctx.get("built_at"), "build_ms": ctx.get("build_ms"), "kb_mode": ctx.get("kb_mode"),
                        "export_date": ctx.get("export_date")},
            "memory_recalled": len(memories), "llm": llm, "trace_id": trace_id if aom.enabled else None,
            "governed": aom.enabled, "total_ms": round((time.perf_counter() - t0) * 1000, 1),
            "export_date": STATE.get("export_date"), "site_id": site_id if personal else None,
        }
        metrics.assistant(result)
        await _append_chat(tech_id, message, result)
        if personal and site:
            await _remember(site["site_id"], tech_id, message, intent, session_id)
        return result
    finally:
        current_trace.reset(token)


async def _append_chat(tech_id: str, message: str, result: dict):
    doc = await store.get("assistant", chat_id(tech_id)) or {
        "type": "assistant", "tech_id": tech_id, "messages": [], "answers": {}, "channels": [tech_channel(tech_id)]}
    now = now_iso()
    doc["messages"] = (doc["messages"] + [
        {"id": uuid.uuid4().hex[:12], "role": "tech", "text": message, "at": now, "site_id": result.get("site_id")},
        {"id": uuid.uuid4().hex[:12], "role": "assistant", "text": result["reply"], "at": now,
         "intent": result["intent"], "actions": result["actions"], "context": result["context"], "llm": result["llm"],
         "sources": result["sources"], "site_id": result.get("site_id")},
    ])[-40:]
    # Answer cache the phone can reuse offline for the same (normalized) question on the same site.
    akey = f"{result.get('site_id') or '-'}|{_norm(message)[:120]}"
    doc["answers"][akey] = {"reply": result["reply"], "intent": result["intent"], "at": now, "actions": result["actions"]}
    if len(doc["answers"]) > 60:
        doc["answers"] = dict(list(doc["answers"].items())[-60:])
    doc["updated_at"] = now
    await store.upsert("assistant", chat_id(tech_id), doc)
