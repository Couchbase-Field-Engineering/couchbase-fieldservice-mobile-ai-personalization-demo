"""Knowledge Base documents published to AOM by the daily loader.

Two kinds:

* **Site profile** - one per site due for a visit soon, rendered from that
  morning's Databricks row as plain prose. The assistant retrieves it with a
  `document_id`-scoped search, so a question about one tower can only ever be
  grounded in *that* site's profile, never a neighbour's that happens to be
  semantically close.
* **Field Maintenance Runbook** - procedures, parts, safety, SLA and
  approval policy. Contains no site data, so answers grounded only in it are
  safe to share across technicians through AOM's LLM cache.

FAQ entries are also synced to the phone inside the catalog document, so the
app can answer the common questions offline from Couchbase Lite.
"""
from __future__ import annotations

from . import catalog as C

FAQ = [
    {"q": "How does a budget override work?",
     "a": "Every site has a quarterly maintenance budget. If the parts on a work order would take the site past what is left "
          "of it (the limit minus what is already committed), submit it as a budget override with a reason. Field Ops reviews "
          "it in the Agent Operations Manager's Approvals page; once approved, the shortfall becomes a one-time extension and "
          "the work order is closed automatically. Sites on an access hold can't be overridden - the hold has to be released first.",
     "keywords": ["budget", "override", "limit", "over budget", "approval", "field ops", "authorization", "authorisation", "spend"]},
    {"q": "When do I need an outage window?",
     "a": "Any service-affecting step needs a planned outage window from the NOC before you start: swapping a radio, a "
          "baseband card, a backhaul optic or a microwave ODU, breaking an RF path, or powering down a cabinet. Request it "
          "from the app with the duration (5 to 240 minutes) and a reason; the NOC approves it in the Agent Operations "
          "Manager and the grant syncs back to the work order. Hot-swap parts such as rectifier modules, fan trays and "
          "filters do not need a window.",
     "keywords": ["outage", "window", "noc", "service affecting", "service-affecting", "off-air", "off air", "downtime", "maintenance window", "lock"]},
    {"q": "What is the difference between preventive and corrective maintenance?",
     "a": "Preventive maintenance is the scheduled visit: the site type's checklist (battery test, filters, connector and "
          "grounding inspection, generator run) plus the wear parts the asset-health model predicts are close to failure. "
          "Corrective maintenance is driven by an open alarm or a trouble ticket: find the fault, fit the part, clear the "
          "alarm. The app builds one work plan with both halves, corrective tasks first, so a single visit covers them.",
     "keywords": ["preventive", "corrective", "pm", "cm", "checklist", "scheduled", "difference", "routine", "work type"]},
    {"q": "What happens when a part is not in stock?",
     "a": "The work order still closes. Parts on hand at the serving depot are issued and the rest go on order with an ETA "
          "on the work order card; the work order shows as 'Parts on order' and a follow-up visit is planned for the ETA. "
          "The app shows depot on-hand units on every line so you can pick a substitute before you submit.",
     "keywords": ["out of stock", "backorder", "stock", "available", "availability", "on hand", "substitute", "short", "on order", "depot"]},
    {"q": "How do I test a battery string?",
     "a": "Check float voltage per block (13.5 to 13.8 V for 12 V VRLA at 25 C) and string current, then run a conductance "
          "test on every block. Replace any block more than 20% below the string average or the reference value, and replace "
          "the whole string if more than one block in four fails. Record the readings on the work order. Never open a "
          "battery circuit under load: isolate the string at its breaker first; the second string or the rectifiers carry the site.",
     "keywords": ["battery", "batteries", "string", "float", "conductance", "vrla", "backup", "discharge", "runtime"]},
    {"q": "How do I clear a high VSWR alarm?",
     "a": "Start at the radio and work up the RF path: check the jumper connector torque (5 N·m on 4.3-10), look for water "
          "in the connector and damaged weatherproofing, then sweep the line. Most VSWR alarms after rain are a failed "
          "weatherproofing joint or a kinked jumper. Replace the jumper, re-make the joint with a weatherproofing kit and "
          "confirm the alarm clears. Breaking the RF path takes the sector off-air, so get an outage window first.",
     "keywords": ["vswr", "return loss", "rf", "jumper", "connector", "weatherproof", "pim", "sector", "antenna"]},
    {"q": "What are the rules for climbing a tower?",
     "a": "Only climb-certified technicians climb, never alone: a second certified person and a rescue kit must be on site. "
          "Inspect harness, lanyards and the safety climb before every ascent, check wind (no climbing above 30 mph or with "
          "lightning within 10 miles) and confirm RF exposure limits with the NOC, who can reduce power on the sector you "
          "are working in front of. If the site has a structural or safety hold, do ground-level work only.",
     "keywords": ["climb", "climbing", "tower", "harness", "safety", "rescue", "wind", "lightning", "rf exposure", "height"]},
    {"q": "How do RMAs work?",
     "a": "A part that is dead on arrival, wrong or not needed can be returned within 30 days of being issued. Create the "
          "RMA from the work order line; the cost is credited back to the site's maintenance budget and the part has to be "
          "back at the depot within five business days. Failed units removed from service go back under the vendor's "
          "repair-and-return process with the same RMA number.",
     "keywords": ["return", "returns", "rma", "refund", "doa", "dead on arrival", "wrong part", "faulty", "send back"]},
    {"q": "How do recurring tasks work?",
     "a": "Any wear item can be put on a recurring replacement at a site: a fixed quantity every 2, 4, 8, 12, 26 or 52 weeks "
          "(air filters every 12 weeks, generator service kits every 26). The task is added to the preventive visit that "
          "falls nearest its date, and parts on a recurring task are left out of the model's recommendations so they are "
          "never doubled up.",
     "keywords": ["recurring", "schedule", "cadence", "every", "filter change", "replace every", "interval", "pm schedule"]},
    {"q": "How does the work plan get built?",
     "a": "Each night the asset-health model in Databricks looks at every site's alarms, telemetry, wear and work history "
          "and predicts days-to-failure for its components, with a confidence per part. The daily export lands in Couchbase "
          "and syncs to the technician's phone, where it is checked against depot on-hand units and the site's remaining "
          "budget and combined with open alarms and the site type's checklist. Every work order you close re-ranks the plan "
          "on the next sync.",
     "keywords": ["work plan", "plan", "recommended", "recommendation", "model", "predict", "prediction", "why", "databricks", "asset health"]},
    {"q": "What can I do in the app with no signal?",
     "a": "Everything you need on site: open the site, read its alarms, assets, access notes and history, work through the "
          "plan, pick parts and close out the work order. It is saved to Couchbase Lite on the phone as 'On device' and "
          "syncs through Sync Gateway the moment you have a connection - at the gate, at the next site or back at the "
          "depot. Completions, parts on order and approvals come back to the same work order card.",
     "keywords": ["signal", "offline", "no service", "connection", "wifi", "sync", "shelter", "basement", "dead zone", "coverage"]},
    {"q": "What do the SLA classes mean?",
     "a": "The SLA class sets how fast service has to be restored: Standard 24 hours, Priority 8 hours, Critical 4 hours "
          "(public-safety, hospital or sole-coverage sites) and Hub 2 hours (an aggregation site carrying a cluster of "
          "downstream sites). The class also sets the preventive visit cadence and decides which work order you do first "
          "when two are open.",
     "keywords": ["sla", "class", "tier", "restore", "priority", "critical", "hub", "standard", "response time", "mttr"]},
    {"q": "What is an access hold?",
     "a": "A site goes on access hold when it is not safe or not permitted to work there: a landlord dispute, a failed "
          "structural inspection, an expired permit or a hazard report. No work order can be booked and no override or "
          "outage window can be granted until the Site Access desk releases the hold. Log the visit as 'no access' with "
          "what you found so the desk can follow up.",
     "keywords": ["hold", "access hold", "landlord", "permit", "locked out", "no access", "gate", "site access", "escort"]},
    {"q": "Which depot serves a site?",
     "a": "Sites draw spares from the depot for their state: Northeast (Putnam, CT), Hudson Valley (Montgomery, NY), "
          "Mid-Atlantic (Hagerstown, MD), Southeast (Lakeland, FL), South Central (Arlington, TX), Midwest (Terre Haute, IN) "
          "and West (Ontario, CA). On-hand numbers in the app are that depot's.",
     "keywords": ["depot", "warehouse", "spares", "stores", "where do parts", "which depot"]},
]


def runbook_markdown(export_date: str) -> str:
    lines = [f"# Telecom Field Maintenance Runbook (published {export_date})", "",
             "Procedures, parts, safety, SLA and approval knowledge for the Telecom Field Service Assistant. Contains no "
             "site data.", ""]
    lines += ["## Frequently asked questions", ""]
    for f in FAQ:
        lines += [f"**{f['q']}** {f['a']}", ""]
    lines += ["## SLA classes", ""]
    for t in C.SLA_TIERS:
        lines.append(f"- {t['name']} ({t['code']}): restore within {t['restore_hours']} hours, preventive visit every "
                     f"{t['pm_cadence_days']} days. {t['blurb']}")
    lines += ["", "Work types: " + ", ".join(C.WORK_TYPES) + ".", ""]
    lines += ["## Budget and approval policy", "",
              "Each site has a quarterly maintenance budget. What is available is the limit plus any approved one-time "
              "extension, minus what is already committed. Work orders within the available budget close at once. Work "
              "orders above it need a budget override approved by Field Ops; the approval creates a one-time extension for "
              "the shortfall. Service-affecting work needs an outage window approved by the NOC, between 5 and 240 minutes. "
              "Sites on an access hold cannot have work booked, overridden or windowed until the Site Access desk releases "
              "the hold.", ""]
    lines += ["## Preventive maintenance checklists", ""]
    for code, st in C.SITE_TYPES.items():
        lines.append(f"### {st['name']}")
        for t in st["pm"]:
            lines.append(f"- {t}")
        lines.append("")
    lines += ["## Spare parts", ""]
    for code, cat in C.CATEGORIES.items():
        items = [p for p in C.PRODUCTS if p["category"] == code]
        if not items:
            continue
        lines.append(f"### {cat['name']}")
        for p in items:
            lines.append(f"- {p['name']} ({p['sku']}): ${p['unit_cost']:,.2f} per {p['uom']}, {p['spec']}; "
                         + ("wear item, replaced on a cadence" if p["wear_item"] else "replaced on failure")
                         + (f"; about {p['swap_min']} min to swap" if p["swap_min"] else "")
                         + ("; service-affecting, needs an outage window." if p["service_affecting"] else "; not service-affecting."))
        lines.append("")
    lines += ["## Spares depots", ""]
    for code, dep in C.DEPOTS.items():
        lines.append(f"- {dep['name']} ({code}), {dep['city']}: serves {', '.join(dep['states'])}.")
    lines += ["", "## Site types we maintain", ""]
    for code, st in C.SITE_TYPES.items():
        top = sorted(st["wear"].items(), key=lambda kv: -kv[1])[:4]
        lines.append(f"- {st['name']}: wears through " + ", ".join(C.PRODUCT_BY_SKU[s]["name"].split(",")[0] for s, _ in top) + ".")
    return "\n".join(lines)


def site_profile_markdown(a: dict) -> str:
    s = a["ml_scores"]
    c = a["auth"]
    hist = a.get("work_history", [])[:6]
    hist_txt = "; ".join(f"{o['work_order_id']} on {o['date']} {o.get('work_type', 'maintenance').lower()} ${o['total_usd']:,.2f} "
                         f"({o.get('line_count', len(o.get('lines', [])))} parts, {o.get('source', 'field_tech')})" for o in hist) or "no work orders yet"
    wear = sorted(a.get("wear", {}).items(), key=lambda kv: -float(kv[1].get("per_year") or 0))[:8]
    wear_txt = "; ".join(f"{C.PRODUCT_BY_SKU[sku]['name'].split(',')[0]} ~{v.get('per_year', 0):g}/year, last replaced "
                         f"{v.get('last_replaced')}" for sku, v in wear if sku in C.PRODUCT_BY_SKU)
    rec = "; ".join(f"{int(l['qty'])} x {C.PRODUCT_BY_SKU[l['sku']]['name'].split(',')[0]} ({l.get('confidence', 0):.0%}"
                    + (f", ~{s.get('days_to_failure', {}).get(l['sku'])}d to failure" if s.get("days_to_failure", {}).get(l["sku"]) is not None else "") + ")"
                    for l in s.get("recommended_parts", []) if l["sku"] in C.PRODUCT_BY_SKU) or "none"
    contacts = "; ".join(f"{k['name']} ({k['role']}, {k['phone']})" for k in a.get("contacts", []))
    cluster = (f" Part of the {a['cluster']['cluster_name']} cluster ({a['cluster']['cluster_id']}, "
               f"{a['cluster'].get('sites')} sites).") if a.get("cluster") else ""
    rts = "; ".join(f"{so['qty']} x {so['name'].split(',')[0]} every {so['cadence_weeks']}w" for so in a.get("recurring_tasks", [])) or "none"
    alarms = "; ".join(f"{al['severity']} {al.get('code', '')} {al['text']} (raised {al.get('raised_at', '')[:10]})"
                       for al in a.get("alarms", [])) or "none"
    assets = "; ".join(f"{x['name']} health {x.get('health')}/100 ({x.get('status')})" for x in a.get("assets", [])) or "not listed"
    k = a.get("kpis", {})
    return "\n".join([
        f"# Site profile {a['site_id']}: {a['site_name']}",
        f"Source: Databricks daily export {a['export_date']}, model {s.get('model_version')}.",
        "",
        "## Site",
        f"{a['site_name']} ({a.get('site_code')}) is a {a['site_type_name'].lower()} at {a['address']['street']}, {a['address']['city']}, "
        f"{a['address']['state']} {a['address']['zip']}, in the {a['area_name']} area, drawing spares from "
        f"{C.DEPOTS[a['access']['depot']]['name']}.{cluster} Contacts: {contacts}. "
        f"Access: {a['access']['access_hours']}, {'tower climb required' if a['access'].get('climb_required') else 'no climb required'}. "
        f"Access notes: {a['access'].get('notes') or 'none'}. Field note: {a['visit'].get('signal_note')}.",
        "",
        "## SLA and authorization",
        f"{a['sla']['tier_name']} SLA class, restore within {a['sla'].get('restore_hours')} hours, vendor support agreement "
        f"{a['sla'].get('agreement_id')} renews {a['sla'].get('renewal_date')}. Quarterly maintenance budget "
        f"${c['budget_limit_usd']:,.0f}, committed ${c['committed_usd']:,.2f}"
        + (f", ON ACCESS HOLD for {c.get('hold_days', 0)} days ({c.get('hold_reason')})" if c.get("on_hold") else "") + ".",
        "",
        "## Alarms and assets",
        f"Open alarms: {alarms}.",
        f"Assets: {assets}.",
        f"Availability last 30 days {k.get('availability_30d_pct')}%, {k.get('outage_min_30d')} outage minutes, "
        f"serves about {k.get('subscribers_served', 0):,} subscribers.",
        "",
        "## Work history and wear",
        f"Maintenance spend last 12 months ${a.get('maintenance', {}).get('last_12mo_usd', 0):,.0f} over "
        f"{a.get('maintenance', {}).get('work_orders_last_12mo', 0)} work orders, average ${a.get('maintenance', {}).get('avg_work_order_usd', 0):,.0f}. "
        f"Recent work orders: {hist_txt}.",
        f"Wear: {wear_txt}.",
        f"Recurring tasks: {rts}.",
        "",
        "## Visit",
        f"Last visit {a['visit'].get('last_visit')}, every {a['visit'].get('cadence_days')} days, next {a['visit'].get('next_visit_date')} "
        f"(planned {a['visit'].get('planned_time')}). Notes: {a['visit'].get('notes') or 'none'}.",
        "",
        "## Asset health forecast",
        f"Segment: {s.get('segment')}. Next best action: {s.get('next_best_action')}. Outage risk next 30 days {s.get('outage_risk')}. "
        f"Predicted parts cost ${s.get('predicted_parts_cost_usd', 0):,.0f}. Recommended parts: {rec}. "
        f"Upgrade candidates: {', '.join(C.PRODUCT_BY_SKU[u]['name'].split(',')[0] for u in s.get('upgrade_skus', []) if u in C.PRODUCT_BY_SKU) or 'none'}.",
    ])
