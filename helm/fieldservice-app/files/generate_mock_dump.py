#!/usr/bin/env python3
"""Generate a mock Databricks daily export of network-site asset-health data.

Writes the exact layout a Databricks job produces with
`df.repartition(n).write.mode("overwrite").json(path)`:

    data/databricks-dump/dt=2026-11-13/
        part-00000-<uuid>-c000.json      # JSON Lines, one network site per line
        part-00001-<uuid>-c000.json
        ...
        _SUCCESS
        _manifest.json                   # row/byte counts + schema version (written by the notebook)

Each line is one network site a telecom field technician maintains - a macro
tower, rooftop site, small cell, central office, fiber hub, microwave relay,
edge data center, enterprise premises or DAS venue - joined with its SLA
class, maintenance budget, contacts, access notes, installed assets, open
alarms, the last work orders, wear per part, visit cadence, and the scores
the asset-health model (telco-asset-health-v2.3) produced in Databricks:
per-category failure risk, days-to-failure per component, recommended parts
with a confidence each, upgrade candidates and 30-day outage risk.

Fully deterministic for a given --seed and --export-date, and standard
library only (runs anywhere Python 3.9+ does). Default target is 100 MiB.

    python databricks/generate_mock_dump.py                 # today, 100 MiB
    python databricks/generate_mock_dump.py --export-date 2026-11-13 --target-mb 100
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from app import catalog as C  # noqa: E402

SCHEMA_VERSION = "site_asset_health_v1"
MODEL_VERSION = "telco-asset-health-v2.3"

FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "James", "Isabella", "Lucas", "Mia", "Mason",
         "Amelia", "Ethan", "Harper", "Logan", "Evelyn", "Aiden", "Abigail", "Jackson", "Emily", "Sebastian", "Ella",
         "Mateo", "Scarlett", "Daniel", "Grace", "Henry", "Chloe", "Owen", "Camila", "Wyatt", "Aria", "Carter", "Riley",
         "Jayden", "Nora", "Gabriel", "Lily", "Julian", "Zoey", "Leo", "Hannah", "David", "Layla", "Joseph", "Priya",
         "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Sofia", "Diego", "Valentina", "Carlos", "Lucia", "Andre", "Aaliyah",
         "Marcus", "Keisha", "Tyrone", "Ngozi", "Kwame", "Siobhan", "Declan", "Ingrid", "Lars", "Anika", "Ravi"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
        "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
        "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker",
        "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Patel", "Shah", "Kim", "Chen", "Okafor",
        "O'Brien", "Kowalski", "Nakamura", "Fischer", "Rossi", "Bennett", "Natarajan", "Haddad", "Silva"]
STREETS = ["Main St", "Washington St", "Elm St", "Market St", "Broadway", "Church St", "Maple Ave", "Oak St", "Park Ave",
           "Mill Rd", "Union St", "Water St", "High St", "Center St", "Bridge St", "Front St", "Tower Rd", "Reservoir Rd",
           "Quarry Rd", "Ridge Rd", "Industrial Way", "Depot St"]
NAME_WORDS = {
    "macro_tower": ["Tower", "Macro Tower", "Monopole", "Lattice Tower"],
    "rooftop_site": ["Rooftop", "Rooftop Site", "Building Rooftop"],
    "small_cell": ["Small Cell", "Street Node", "Pole Node"],
    "central_office": ["Central Office", "Exchange", "Switching Center"],
    "fiber_hub": ["Fiber Hub", "OLT Cabinet", "Fiber Cabinet"],
    "microwave_relay": ["Microwave Relay", "Relay Site", "Repeater Site"],
    "edge_pop": ["Edge Data Center", "Edge POP", "Aggregation POP"],
    "enterprise_cpe": ["Enterprise Premises", "Customer Premises", "Business Park Demarc"],
    "das_venue": ["DAS Venue", "In-Building DAS", "Arena DAS"],
}
NAME_PREFIX = ["Harbor", "Riverside", "Main Street", "Village", "Hilltop", "Lakeside", "North End", "Old Town", "Sunrise",
               "Evergreen", "Liberty", "Heritage", "Summit", "Valley", "Bay State", "Granite", "Prairie", "Pinewood",
               "Westside", "Eastgate", "Central", "Metro", "Golden", "Blue Ridge", "Cedar", "Willow", "Oak Hill", "Maple",
               "Reservoir", "Quarry", "Mill Pond", "Fairgrounds", "Airport", "Stadium", "Water Tower", "Ridge"]
ROLES = ["Landlord", "Property Manager", "Building Engineer", "Security Desk", "Site Access Desk", "NOC Duty Manager"]
ACCESS_HOURS = ["24x7 with NOC ticket", "Mon-Fri 8am-5pm, escort required", "Daily 6am-10pm", "24x7, lockbox at gate",
                "Mon-Sat 7am-7pm via building security", "24x7 - call landlord 30 min ahead"]
ACCESS_NOTES = ["Gate on the service road, lockbox on the left post", "Sign in with building security, roof key at the desk",
                "4x4 needed on the access road after rain", "Call the landlord 30 minutes before arrival",
                "Shared compound - our shelter is the grey one at the rear", "Telecom room is in the basement, level B1",
                "", "", ""]
SEGMENTS = ["Stable Performers", "Aging Power Plant", "Weather-Exposed RF", "Capacity Hot Spots", "Chronic Alarm Sites",
            "Recently Upgraded", "Remote Hard-Access", "Backhaul Constrained"]
VENDORS = ["Vendor A", "Vendor B", "Vendor C"]
VISIT_TIMES = ["08:30", "09:15", "10:00", "10:45", "11:30", "13:00", "13:45", "14:30", "15:15", "16:00"]
SOURCES = ["field_tech", "scheduled_pm", "noc_dispatch", "vendor"]

# Alarm text per part category - what the NOC would see for a part close to failure.
ALARMS = {
    "power": [("PWR-201", "Battery string A conductance low", "Test string A and replace failed blocks"),
              ("PWR-114", "Rectifier module fail, N+1 lost", "Replace the failed rectifier module"),
              ("PWR-330", "AC surge protector end of life", "Replace the surge protection cartridge")],
    "cooling": [("ENV-410", "Shelter high temperature", "Replace filters and check the HVAC unit"),
                ("ENV-422", "Cabinet fan fail", "Replace the cabinet fan tray")],
    "radio": [("RAN-510", "Radio unit fan fault", "Replace the radio fan module"),
              ("RAN-534", "GPS timing holdover", "Inspect and replace the GPS antenna kit")],
    "antenna": [("RF-601", "VSWR high, sector 2", "Inspect RF path, replace jumper and re-weatherproof"),
                ("RF-615", "RET actuator not responding", "Replace the RET actuator or control cable")],
    "transport": [("TRN-702", "Backhaul optic receive power low", "Clean and replace the backhaul optic"),
                  ("TRN-720", "Microwave link receive level degraded", "Inspect IF cable and connectors, realign")],
    "fiber": [("FBR-801", "PON port optical power low", "Clean connectors and replace the PON optic"),
              ("FBR-812", "High loss on trunk fiber", "Clean, re-patch and test the fiber path")],
    "site": [("SIT-901", "Tower obstruction light fail", "Replace the obstruction light"),
             ("SIT-910", "Door intrusion sensor fault", "Replace the door sensor")],
}


def clamp(x: float, lo=0.01, hi=0.99) -> float:
    return round(max(lo, min(hi, x)), 3)


def deep_update(base: dict, upd: dict):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


class Gen:
    def __init__(self, export_date: dt.date, seed: int):
        self.d0 = export_date
        self.r = random.Random(seed)
        self.site_seq = 200000
        self.tech_seq = 2000
        self.emp_seq = 500000
        self.wo_seq = 0
        self.alarm_seq = 40000

    # -- technicians and areas ------------------------------------------------
    def area(self, base_code: str, variant: int, tech: dict | None = None) -> dict:
        base = C.AREAS[base_code]
        aid = base_code if variant == 0 else f"{base_code}-{variant:02d}"
        name = base["name"] if variant == 0 else f"{base['name']} {variant + 1}"
        if tech is None:
            self.tech_seq += 1
            self.emp_seq += self.r.randint(3, 97)
            first, last = self.r.choice(FIRST), self.r.choice(LAST)
            tech = {"tech_id": f"T{self.tech_seq}", "employee_id": f"{self.emp_seq}", "first_name": first, "last_name": last,
                    "email": f"{first.lower()}.{last.lower().replace(chr(39), '')}@telco.example.com",
                    "certifications": self.r.sample(["Tower climb", "RF awareness", "Fiber splicing", "DC power", "Generator"], k=3)}
        return {"area_id": aid, "area_name": name, "state": base["state"], "cities": base["cities"], "tech": tech,
                "prefix": base_code.split("-")[-1]}

    # -- sites ------------------------------------------------------------------
    def next_site_id(self):
        self.site_seq += 1
        return f"S{self.site_seq:08d}"

    def contact(self, role=None):
        first, last = self.r.choice(FIRST), self.r.choice(LAST)
        return {"name": f"{first} {last}", "role": role or self.r.choice(ROLES),
                "phone": f"({self.r.randint(201, 989)}) 555-{self.r.randint(100, 199):04d}",
                "email": f"{first.lower()}@{last.lower().replace(chr(39), '')}.example.com"}

    def work_order(self, when: dt.date, wear: dict, cadence: int) -> dict:
        r = self.r
        self.wo_seq += 1
        lines = []
        for sku, per_year in wear.items():
            expect = per_year * cadence / 365.0
            if r.random() < min(0.75, expect * 1.4 + 0.08):
                qty = max(1, int(round(expect * r.uniform(0.7, 1.6))))
                unit = C.part_cost(sku)
                lines.append({"sku": sku, "name": C.PRODUCT_BY_SKU[sku]["name"], "qty": qty, "unit_cost": unit,
                              "line_total": round(unit * qty, 2)})
        if not lines:
            sku = next(iter(wear))
            unit = C.part_cost(sku)
            lines = [{"sku": sku, "name": C.PRODUCT_BY_SKU[sku]["name"], "qty": 1, "unit_cost": unit, "line_total": unit}]
        total = round(sum(l["line_total"] for l in lines), 2)
        return {"work_order_id": f"WO-{when:%y%m%d}-{10000 + self.wo_seq % 90000}", "date": when.isoformat(), "status": "completed",
                "source": r.choices(SOURCES, weights=[40, 40, 15, 5])[0],
                "work_type": r.choices(C.WORK_TYPES, weights=[62, 28, 6, 4])[0], "line_count": len(lines), "lines": lines,
                "parts_usd": total, "total_usd": total,
                "backordered": [] if r.random() > 0.08 else [{"sku": lines[0]["sku"], "name": lines[0]["name"], "qty": 1}]}

    def alarm(self, category: str, severity: str, days_ago: int = 0, pick: int | None = None) -> dict:
        self.alarm_seq += 1
        code, text, action = ALARMS[category][pick if pick is not None else self.r.randrange(len(ALARMS[category]))]
        raised = dt.datetime.combine(self.d0 - dt.timedelta(days=days_ago), dt.time(self.r.randint(0, 5), self.r.randint(0, 59)))
        return {"alarm_id": f"AL{self.alarm_seq}", "severity": severity, "code": code, "text": text, "action": action,
                "category": category, "raised_at": raised.strftime("%Y-%m-%dT%H:%M:%SZ")}

    def site(self, area: dict, stype: str, overrides: dict | None = None, name: str | None = None,
             cluster: dict | None = None, due_today: bool = False) -> dict:
        r = self.r
        sid = self.next_site_id()
        city, state, zipc = r.choice(area["cities"])
        st = C.SITE_TYPES[stype]
        wear_rate = {sku: round(m * r.uniform(0.6, 1.5), 2) for sku, m in st["wear"].items() if r.random() < 0.9}
        if not wear_rate:
            wear_rate = dict(st["wear"])
        tier = cluster["tier"] if cluster else r.choices(["STANDARD", "PRIORITY", "CRITICAL"], weights=[48, 36, 16])[0]
        tier_def = C.TIER_BY_CODE[tier]
        cadence = r.choice([14, 30, 30, 30, 60, 60, 90]) if tier == "STANDARD" else r.choice([14, 30, 30, 60])
        # last work orders, newest first
        history = []
        when = self.d0 - dt.timedelta(days=r.randint(2, cadence))
        for _ in range(r.randint(5, 12)):
            history.append(self.work_order(when, wear_rate, cadence))
            when -= dt.timedelta(days=int(cadence * r.uniform(0.7, 1.4)) or 1)
        last_wo = history[0]
        last_by_sku = {}
        for o in history:
            for l in o["lines"]:
                last_by_sku.setdefault(l["sku"], o["date"])
        oldest = history[-1]["date"]
        wear = {sku: {"per_year": m, "last_replaced": last_by_sku.get(sku, (dt.date.fromisoformat(oldest)
                                                                              - dt.timedelta(days=r.randint(30, 400))).isoformat()),
                      "last_qty": next((l["qty"] for o in history for l in o["lines"] if l["sku"] == sku), 1)}
                for sku, m in wear_rate.items()}
        spend_12 = round(sum(o["total_usd"] for o in history), 2)
        limit = r.choice([5000, 7500, 10000, 15000, 25000]) if tier != "STANDARD" else r.choice([2500, 5000, 7500])
        committed = round(min(limit * r.uniform(0.05, 0.85), last_wo["total_usd"] * r.uniform(0.6, 2.4) + r.uniform(0, 600)), 2)
        hold_days = r.choices([0] * 70 + [21, 68], k=1)[0]
        on_hold = hold_days > 0
        # model: recommended parts are the wear items closest to predicted failure
        in_service = {sku: (self.d0 - dt.date.fromisoformat(w["last_replaced"])).days for sku, w in wear.items()}
        recommended, dtf_map = [], {}
        for sku, w in wear.items():
            life_days = 365.0 / max(w["per_year"], 0.05) * (w["last_qty"] or 1) * r.uniform(0.85, 1.2)
            dtf = int(round(life_days - in_service[sku]))
            dtf_map[sku] = dtf
            if dtf <= 21 and C.PRODUCT_BY_SKU[sku]["wear_item"]:
                qty = max(1, int(round(w["per_year"] * cadence / 365.0 * 1.1)))
                conf = clamp(0.95 - max(0, dtf) * 0.02 + r.gauss(0, 0.04))
                recommended.append({"sku": sku, "qty": qty, "confidence": conf,
                                    "reason": "Past predicted end of life" if dtf <= 0 else "Health trend below threshold"})
        recommended.sort(key=lambda s: -s["confidence"])
        recommended = recommended[:8]
        spare_pool = [p["sku"] for p in C.PRODUCTS if not p["wear_item"] and p["sku"] not in wear_rate and p["unit_cost"] < 2000]
        upgrades = r.sample(spare_pool, k=min(2, len(spare_pool)))
        # alarms: parts predicted to fail within a few days usually already alarm
        alarms = []
        seen_cat = set()
        for rec in recommended:
            cat = C.PRODUCT_BY_SKU[rec["sku"]]["category"]
            d = dtf_map[rec["sku"]]
            if cat in ALARMS and cat not in seen_cat and d <= 5 and r.random() < 0.7:
                seen_cat.add(cat)
                alarms.append(self.alarm(cat, "major" if d <= 1 else "minor", days_ago=r.randint(0, 4)))
        risks = {C.CATEGORIES[cat]["risk"]: clamp(0.1 + r.random() * 0.5) for cat in C.CATEGORIES}
        for rec in recommended:
            risks[C.CATEGORIES[C.PRODUCT_BY_SKU[rec["sku"]]["category"]]["risk"]] = clamp(0.55 + r.random() * 0.4)
        outage = clamp(0.06 + 0.12 * len(alarms) + 0.03 * len(recommended) + r.gauss(0, 0.05))
        assets = []
        for i, (cat, aname) in enumerate(st["assets"]):
            risk = risks[C.CATEGORIES[cat]["risk"]]
            health = int(max(22, min(99, 100 - risk * 70 + r.gauss(0, 6))))
            assets.append({"asset_id": f"{sid}-A{i + 1:02d}", "category": cat, "name": aname, "vendor": r.choice(VENDORS),
                           "installed": str(self.d0.year - r.randint(1, 12)), "health": health,
                           "status": "degraded" if health < 60 else "ok"})
        next_visit = self.d0 + dt.timedelta(days=r.randint(0, cadence))
        predicted = round(sum(C.part_cost(s["sku"]) * s["qty"] for s in recommended) * r.uniform(0.9, 1.3), 2)
        base_name = name or f"{r.choice(NAME_PREFIX)} {r.choice(NAME_WORDS[stype])}"
        outage_min = int(max(0, r.gauss(12, 18))) if alarms else int(max(0, r.gauss(2, 4)))
        row = {
            "export_date": self.d0.isoformat(),
            "schema_version": SCHEMA_VERSION,
            "site_id": sid,
            "site_name": base_name,
            "site_code": f"{area['prefix']}-{r.randint(100, 9899):04d}",
            "site_type": stype, "site_type_name": st["name"],
            "cluster": {"cluster_id": cluster["cluster_id"], "cluster_name": cluster["cluster_name"], "sites": cluster["sites"]} if cluster else None,
            "address": {"street": f"{r.randint(10, 1899)} {r.choice(STREETS)}", "city": city, "state": state, "zip": zipc},
            "area_id": area["area_id"], "area_name": area["area_name"],
            "assigned_tech": dict(area["tech"]),
            "contacts": [self.contact("Landlord" if r.random() < 0.6 else "Property Manager"), self.contact("NOC Duty Manager")]
                        + ([self.contact("Security Desk")] if r.random() < 0.3 else []),
            "sla": {"tier": tier, "tier_name": tier_def["name"], "restore_hours": tier_def["restore_hours"],
                    "pm_cadence_days": tier_def["pm_cadence_days"],
                    "agreement_id": cluster["agreement_id"] if cluster else f"VSA-{r.randint(100000, 999999)}",
                    "renewal_date": (self.d0 + dt.timedelta(days=r.randint(15, 360))).isoformat(),
                    "on_air_since": str(self.d0.year - r.randint(1, 18))},
            "auth": {"budget_limit_usd": float(limit), "committed_usd": committed, "period": f"{self.d0.year}-Q{(self.d0.month - 1) // 3 + 1}",
                     "hold_days": hold_days, "on_hold": on_hold,
                     "hold_reason": r.choice(["Landlord access dispute", "Structural inspection overdue", "Permit renewal pending"]) if on_hold else None,
                     "temporary_extension_usd": 0},
            "access": {"access_hours": r.choice(ACCESS_HOURS), "climb_required": stype in ("macro_tower", "microwave_relay") and r.random() < 0.7,
                       "notes": r.choice(ACCESS_NOTES), "depot": C.depot_for_state(state)},
            "visit": {"last_visit": (self.d0 - dt.timedelta(days=r.randint(1, cadence))).isoformat(), "cadence_days": cadence,
                      "next_visit_date": next_visit.isoformat(), "planned_time": r.choice(VISIT_TIMES),
                      "signal_note": r.choice(C.SIGNAL_NOTES), "notes": ""},
            "assets": assets,
            "alarms": alarms,
            "kpis": {"availability_30d_pct": round(100 - outage_min / 432.0, 3), "outage_min_30d": outage_min,
                     "subscribers_served": r.choice([180, 420, 900, 1800, 3200, 5400, 9800, 16000])},
            "work_history": history,
            "wear": wear,
            "maintenance": {"last_12mo_usd": spend_12, "ytd_usd": round(spend_12 * 0.83, 2),
                            "avg_work_order_usd": round(spend_12 / len(history), 2), "work_orders_last_12mo": len(history),
                            "category_mix": self._mix(history)},
            "recurring_tasks": [],
            "ml_scores": {
                "model_version": MODEL_VERSION, "scored_at": f"{self.d0.isoformat()}T04:48:11Z",
                **risks,
                "outage_risk": outage,
                "predicted_parts_cost_usd": predicted,
                "days_to_failure": dtf_map,
                "recommended_parts": recommended,
                "upgrade_skus": upgrades,
                "segment": r.choice(SEGMENTS),
                "next_best_action": "clear_access_hold" if on_hold else ("corrective" if alarms else ("preventive" if recommended else "inspect")),
            },
            "flags": {"generator_backup": any("generator" in a["name"].lower() for a in assets), "shared_site": r.random() < 0.3},
            "_ingest": {"source_table": "telco_prod.network360.site_asset_health_daily",
                        "pipeline": "site_asset_health_daily_export", "dbr_version": "16.4 LTS"},
        }
        if overrides:
            deep_update(row, overrides)
            # A hand-written recommendation should not sit next to a part fitted last month.
            for rec in row["ml_scores"]["recommended_parts"]:
                w = row["wear"].setdefault(rec["sku"], {"per_year": st["wear"].get(rec["sku"], 1.0), "last_qty": rec["qty"]})
                age = max(75, int(365.0 / max(w["per_year"], 0.2) * r.uniform(0.9, 1.15)))
                w["last_replaced"] = (self.d0 - dt.timedelta(days=age)).isoformat()
        # Each alarm lands on the asset it names (else the first asset in its category).
        for al in row["alarms"]:
            same = [a for a in row["assets"] if a["category"] == al["category"]]
            words = {w for w in al["text"].lower().replace(",", " ").split() if len(w) > 3}
            hit = next((a for a in same if words & set(a["name"].lower().replace(",", " ").split())), same[0] if same else None)
            if hit:
                hit["status"], hit["health"] = "alarm", min(hit["health"], 38 if al["severity"] != "minor" else 52)
        if due_today:
            row["visit"].update(next_visit_date=self.d0.isoformat(), cadence_days=30,
                                last_visit=(self.d0 - dt.timedelta(days=30)).isoformat())
        return row

    def _mix(self, history):
        tot = {}
        for o in history:
            for l in o["lines"]:
                cat = C.PRODUCT_BY_SKU[l["sku"]]["category"]
                tot[cat] = tot.get(cat, 0) + l["line_total"]
        s = sum(tot.values()) or 1
        return {k: round(v / s, 3) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])}

    def area_rows(self, area: dict, n: int):
        types = list(C.SITE_TYPES)
        weights = [26, 14, 18, 6, 12, 6, 3, 10, 5]
        for _ in range(n):
            yield self.site(area, self.r.choices(types, weights=weights)[0])

    # -- personas -------------------------------------------------------------------
    def personas(self):
        """Hand-built demo technicians and the stops on their route today.
        Their `next_visit_date` is the export date, so the story is the same
        in every daily export."""
        d0 = self.d0.isoformat()
        rows = []
        ok_auth = {"hold_days": 0, "on_hold": False, "hold_reason": None}

        # 1. Maya Chen - Boston North Shore.
        maya = {"tech_id": "T1001", "employee_id": "204817", "first_name": "Maya", "last_name": "Chen",
                "email": "maya.chen@telco.example.com", "certifications": ["Tower climb", "DC power", "RF awareness"]}
        t1 = self.area("A-BOS-NS", 0, maya)
        rows.append(self.site(t1, "macro_tower", name="Salem Harbor Tower", due_today=True, overrides={
            "site_id": "S00101001", "site_code": "BOS-0417",
            "address": {"street": "212 Derby St", "city": "Salem", "state": "MA", "zip": "01970"},
            "contacts": [{"name": "Frank Molloy", "role": "Landlord", "phone": "(978) 555-0142", "email": "frank@harborwharf.example.com"},
                         {"name": "Dee Alvarez", "role": "NOC Duty Manager", "phone": "(978) 555-0143", "email": "noc@telco.example.com"}],
            "sla": {"tier": "CRITICAL", "tier_name": "Critical", "restore_hours": 4, "pm_cadence_days": 30, "agreement_id": "VSA-448120",
                    "renewal_date": (self.d0 + dt.timedelta(days=95)).isoformat(), "on_air_since": "2011"},
            "auth": {"budget_limit_usd": 10000.0, "committed_usd": 8480.40, **ok_auth},
            "access": {"access_hours": "24x7, lockbox at gate", "climb_required": False,
                       "notes": "Steel equipment shelter at the base of the tower - door code from the NOC", "depot": "DEP-NE"},
            "visit": {"planned_time": "08:30", "signal_note": "Steel equipment shelter - no signal inside"},
            "alarms": [self.alarm("power", "major", days_ago=1, pick=0), self.alarm("cooling", "minor", days_ago=3, pick=0)],
            "kpis": {"availability_30d_pct": 99.94, "outage_min_30d": 26, "subscribers_served": 9800},
            "ml_scores": {"segment": "Aging Power Plant", "next_best_action": "corrective", "outage_risk": 0.62,
                          "power_failure_risk": 0.91, "cooling_failure_risk": 0.7, "antenna_failure_risk": 0.62,
                          "transport_failure_risk": 0.55, "site_failure_risk": 0.5, "fiber_failure_risk": 0.45,
                          "recommended_parts": [
                              {"sku": "FS-PWR-2204", "qty": 4, "confidence": 0.96, "reason": "String A conductance 28% below reference"},
                              {"sku": "FS-CLG-3101", "qty": 1, "confidence": 0.93, "reason": "Shelter temperature trending up"},
                              {"sku": "FS-ANT-5101", "qty": 1, "confidence": 0.88, "reason": "VSWR drift on sector 2 after rain"},
                              {"sku": "FS-PWR-2310", "qty": 1, "confidence": 0.84, "reason": "Surge counter at end-of-life"},
                              {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.74, "reason": "Due on this visit"},
                              {"sku": "FS-SIT-8162", "qty": 1, "confidence": 0.7, "reason": "Due on this visit"},
                              {"sku": "FS-TRN-6101", "qty": 1, "confidence": 0.48, "reason": "Receive power slowly degrading"},
                              {"sku": "FS-SIT-8121", "qty": 1, "confidence": 0.4, "reason": "Corrosion noted on last visit"}],
                          "days_to_failure": {"FS-PWR-2204": 1, "FS-CLG-3101": 4, "FS-ANT-5101": 6, "FS-PWR-2310": 9,
                                              "FS-FBR-7110": 12, "FS-SIT-8162": 14, "FS-TRN-6101": 19, "FS-SIT-8121": 21},
                          "upgrade_skus": ["FS-PWR-2260", "FS-TLS-9110"], "predicted_parts_cost_usd": 1890.0},
        }))
        rows.append(self.site(t1, "central_office", name="Salem Central Office", due_today=True, overrides={
            "site_id": "S00101002", "site_code": "BOS-0002",
            "address": {"street": "88 Washington St", "city": "Salem", "state": "MA", "zip": "01970"},
            "sla": {"tier": "HUB", "tier_name": "Hub", "restore_hours": 2, "pm_cadence_days": 30, "agreement_id": "VSA-391877"},
            "auth": {"budget_limit_usd": 25000.0, "committed_usd": 6410.15, **ok_auth},
            "access": {"depot": "DEP-NE", "access_hours": "24x7 with NOC ticket", "climb_required": False,
                       "notes": "Sign in at the security desk; power room is on level B1"},
            "visit": {"planned_time": "10:00", "signal_note": "Basement telecom room - no signal"},
            "alarms": [self.alarm("power", "major", days_ago=0, pick=1)],
            "kpis": {"availability_30d_pct": 99.999, "outage_min_30d": 0, "subscribers_served": 16000},
            "ml_scores": {"segment": "Aging Power Plant", "next_best_action": "corrective", "outage_risk": 0.34,
                          "power_failure_risk": 0.88, "cooling_failure_risk": 0.66,
                          "recommended_parts": [
                              {"sku": "FS-PWR-2101", "qty": 2, "confidence": 0.94, "reason": "Module 3 failed, module 5 fan current high"},
                              {"sku": "FS-CLG-3101", "qty": 2, "confidence": 0.9, "reason": "Differential pressure high"},
                              {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.78, "reason": "Due on this visit"},
                              {"sku": "FS-SIT-8144", "qty": 1, "confidence": 0.7, "reason": "Inspection tag expires this month"}],
                          "days_to_failure": {"FS-PWR-2101": 0, "FS-CLG-3101": 5, "FS-FBR-7110": 10, "FS-SIT-8144": 12},
                          "upgrade_skus": ["FS-PWR-2260"], "predicted_parts_cost_usd": 2610.0},
        }))
        rows.append(self.site(t1, "rooftop_site", name="Beverly Hospital Rooftop", due_today=True, overrides={
            "site_id": "S00101003", "site_code": "BOS-0388",
            "address": {"street": "14 Cabot St", "city": "Beverly", "state": "MA", "zip": "01915"},
            "sla": {"tier": "CRITICAL", "tier_name": "Critical", "restore_hours": 4, "pm_cadence_days": 30, "agreement_id": "VSA-520034"},
            "auth": {"budget_limit_usd": 7500.0, "committed_usd": 860.0, **ok_auth},
            "access": {"depot": "DEP-NE", "access_hours": "Mon-Sat 7am-7pm via building security", "climb_required": False,
                       "notes": "Roof key at facilities; no work during helicopter operations"},
            "visit": {"planned_time": "11:30", "signal_note": "Rooftop plant room, weak LTE"},
            "alarms": [self.alarm("antenna", "major", days_ago=2, pick=0)],
            "ml_scores": {"segment": "Weather-Exposed RF", "outage_risk": 0.41, "next_best_action": "corrective",
                          "antenna_failure_risk": 0.9, "radio_failure_risk": 0.6,
                          "recommended_parts": [
                              {"sku": "FS-ANT-5110", "qty": 2, "confidence": 0.95, "reason": "VSWR 1.9 on sector 2"},
                              {"sku": "FS-ANT-5101", "qty": 1, "confidence": 0.9, "reason": "Water ingress pattern"},
                              {"sku": "FS-RAN-4133", "qty": 1, "confidence": 0.78, "reason": "Fan speed variance"},
                              {"sku": "FS-SIT-8162", "qty": 1, "confidence": 0.62, "reason": "Due on this visit"}],
                          "days_to_failure": {"FS-ANT-5110": 2, "FS-ANT-5101": 3, "FS-RAN-4133": 11, "FS-SIT-8162": 13},
                          "upgrade_skus": ["FS-TLS-9101"], "predicted_parts_cost_usd": 430.0},
        }))
        rows.append(self.site(t1, "fiber_hub", name="Highland Ave Fiber Hub", due_today=True, overrides={
            "site_id": "S00101004", "site_code": "BOS-F112",
            "address": {"street": "401 Highland Ave", "city": "Salem", "state": "MA", "zip": "01970"},
            "sla": {"tier": "PRIORITY", "tier_name": "Priority", "restore_hours": 8, "pm_cadence_days": 60, "agreement_id": "VSA-611209",
                    "renewal_date": (self.d0 + dt.timedelta(days=28)).isoformat()},
            "auth": {"budget_limit_usd": 5000.0, "committed_usd": 310.0, **ok_auth},
            "access": {"depot": "DEP-NE", "climb_required": False, "notes": "Street cabinet - cone off the parking bay"},
            "visit": {"planned_time": "13:30", "signal_note": "Good signal"},
            "alarms": [],
            "ml_scores": {"segment": "Stable Performers", "outage_risk": 0.14, "next_best_action": "preventive",
                          "fiber_failure_risk": 0.72, "cooling_failure_risk": 0.58,
                          "recommended_parts": [
                              {"sku": "FS-FBR-7130", "qty": 1, "confidence": 0.9, "reason": "PON 3 transmit power drifting"},
                              {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.8, "reason": "Due on this visit"},
                              {"sku": "FS-CLG-3110", "qty": 1, "confidence": 0.77, "reason": "Fan bearing noise signature"}],
                          "days_to_failure": {"FS-FBR-7130": 5, "FS-FBR-7110": 8, "FS-CLG-3110": 10},
                          "upgrade_skus": ["FS-CLG-3150", "FS-SIT-8110"], "predicted_parts_cost_usd": 420.0},
        }))
        rows.append(self.site(t1, "small_cell", name="Elliott St Small Cell", due_today=True, overrides={
            "site_id": "S00101005", "site_code": "BOS-S731",
            "address": {"street": "9 Elliott St", "city": "Beverly", "state": "MA", "zip": "01915"},
            "sla": {"tier": "STANDARD", "tier_name": "Standard", "restore_hours": 24, "pm_cadence_days": 90, "agreement_id": "VSA-702881",
                    "renewal_date": (self.d0 + dt.timedelta(days=30)).isoformat()},
            "auth": {"budget_limit_usd": 2500.0, "committed_usd": 0.0, **ok_auth},
            "access": {"depot": "DEP-NE", "climb_required": False, "notes": "Utility pole - bucket truck booked for 3pm"},
            "visit": {"planned_time": "15:00", "signal_note": "Good signal"},
            "alarms": [],
            "ml_scores": {"segment": "Recently Upgraded", "outage_risk": 0.08, "next_best_action": "preventive",
                          "recommended_parts": [
                              {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.9, "reason": "Due on this visit"},
                              {"sku": "FS-PWR-2310", "qty": 1, "confidence": 0.86, "reason": "Surge counter at end-of-life"},
                              {"sku": "FS-SIT-8162", "qty": 1, "confidence": 0.6, "reason": "Due on this visit"}],
                          "days_to_failure": {"FS-FBR-7110": 4, "FS-PWR-2310": 7, "FS-SIT-8162": 14},
                          "upgrade_skus": ["FS-SIT-8130"], "predicted_parts_cost_usd": 150.0},
        }))
        for a in self.area_rows(t1, 52):
            if a["visit"]["next_visit_date"] == d0:
                a["visit"]["next_visit_date"] = (self.d0 + dt.timedelta(days=1)).isoformat()
            rows.append(a)

        # 2. Devon Walker - Hudson Valley, long drives and mountaintop relays.
        devon = {"tech_id": "T1002", "employee_id": "318552", "first_name": "Devon", "last_name": "Walker",
                 "email": "devon.walker@telco.example.com", "certifications": ["Tower climb", "Generator", "Fiber splicing"]}
        t2 = self.area("A-NY-HV", 0, devon)
        rows.append(self.site(t2, "microwave_relay", name="Catskill Ridge Microwave Relay", due_today=True, overrides={
            "site_id": "S00102001", "site_code": "HV-0091",
            "address": {"street": "Ridge Rd, mile 6", "city": "Catskill", "state": "NY", "zip": "12414"},
            "sla": {"tier": "HUB", "tier_name": "Hub", "restore_hours": 2, "pm_cadence_days": 30, "agreement_id": "VSA-377410"},
            "auth": {"budget_limit_usd": 15000.0, "committed_usd": 3120.0, **ok_auth},
            "access": {"depot": "DEP-NY", "access_hours": "24x7, lockbox at gate", "climb_required": True,
                       "notes": "4x4 needed on the access road after rain; generator fuel gauge reads low"},
            "visit": {"planned_time": "08:30", "signal_note": "Mountaintop relay - dead zone on the access road"},
            "alarms": [self.alarm("transport", "major", days_ago=1, pick=1)],
            "kpis": {"availability_30d_pct": 99.91, "outage_min_30d": 39, "subscribers_served": 5400},
            "ml_scores": {"segment": "Remote Hard-Access", "outage_risk": 0.57, "next_best_action": "corrective",
                          "transport_failure_risk": 0.9, "power_failure_risk": 0.75, "site_failure_risk": 0.6,
                          "recommended_parts": [
                              {"sku": "FS-TRN-6152", "qty": 1, "confidence": 0.95, "reason": "Receive level down 6 dB, water in IF connector"},
                              {"sku": "FS-PWR-2415", "qty": 1, "confidence": 0.9, "reason": "Generator run hours since service"},
                              {"sku": "FS-SIT-8101", "qty": 1, "confidence": 0.84, "reason": "Lamp current dropping"},
                              {"sku": "FS-CLG-3101", "qty": 1, "confidence": 0.72, "reason": "Due on this visit"}],
                          "days_to_failure": {"FS-TRN-6152": 1, "FS-PWR-2415": 5, "FS-SIT-8101": 6, "FS-CLG-3101": 12},
                          "upgrade_skus": ["FS-PWR-2420"], "predicted_parts_cost_usd": 480.0},
        }))
        rows.append(self.site(t2, "central_office", name="Rhinebeck Central Office", due_today=True, overrides={
            "site_id": "S00102002", "site_code": "HV-0003",
            "address": {"street": "6 Mill St", "city": "Rhinebeck", "state": "NY", "zip": "12572"},
            "sla": {"tier": "CRITICAL", "tier_name": "Critical", "restore_hours": 4, "pm_cadence_days": 30, "agreement_id": "VSA-299150"},
            "auth": {"budget_limit_usd": 15000.0, "committed_usd": 2890.0, **ok_auth},
            "access": {"depot": "DEP-NY", "climb_required": False},
            "visit": {"planned_time": "11:00", "signal_note": "Basement telecom room - no signal"},
            "alarms": [self.alarm("cooling", "minor", days_ago=2, pick=0)],
            "ml_scores": {"segment": "Chronic Alarm Sites", "outage_risk": 0.22, "next_best_action": "preventive",
                          "cooling_failure_risk": 0.86,
                          "recommended_parts": [
                              {"sku": "FS-CLG-3101", "qty": 2, "confidence": 0.94, "reason": "High-temperature alarm, filters 14 weeks old"},
                              {"sku": "FS-CLG-3122", "qty": 1, "confidence": 0.82, "reason": "Compressor start current rising"},
                              {"sku": "FS-FBR-7101", "qty": 1, "confidence": 0.75, "reason": "Due on this visit"}],
                          "days_to_failure": {"FS-CLG-3101": 3, "FS-CLG-3122": 8, "FS-FBR-7101": 12},
                          "upgrade_skus": ["FS-CLG-3150"], "predicted_parts_cost_usd": 250.0},
        }))
        rows.append(self.site(t2, "macro_tower", name="Kingston North Tower", due_today=True, overrides={
            "site_id": "S00102003", "site_code": "HV-0225",
            "address": {"street": "25 N Front St", "city": "Kingston", "state": "NY", "zip": "12401"},
            "sla": {"tier": "STANDARD", "tier_name": "Standard", "restore_hours": 24, "pm_cadence_days": 90, "agreement_id": "VSA-805567"},
            "auth": {"budget_limit_usd": 5000.0, "committed_usd": 190.0, **ok_auth},
            "access": {"depot": "DEP-NY", "climb_required": True},
            "visit": {"planned_time": "13:30", "signal_note": "Good signal"},
            "alarms": [],
            "ml_scores": {"segment": "Stable Performers", "outage_risk": 0.1, "next_best_action": "preventive",
                          "recommended_parts": [
                              {"sku": "FS-CLG-3101", "qty": 2, "confidence": 0.9, "reason": "Due on this visit"},
                              {"sku": "FS-ANT-5101", "qty": 1, "confidence": 0.82, "reason": "Weatherproofing age"}],
                          "days_to_failure": {"FS-CLG-3101": 5, "FS-ANT-5101": 6},
                          "upgrade_skus": ["FS-TLS-9110"], "predicted_parts_cost_usd": 160.0},
        }))
        rows.append(self.site(t2, "enterprise_cpe", name="Poughkeepsie Medical Campus", due_today=True, overrides={
            "site_id": "S00102004", "site_code": "HV-E410",
            "address": {"street": "40 Garden St", "city": "Poughkeepsie", "state": "NY", "zip": "12601"},
            "sla": {"tier": "PRIORITY", "tier_name": "Priority", "restore_hours": 8, "pm_cadence_days": 60, "agreement_id": "VSA-460239"},
            "auth": {"budget_limit_usd": 7500.0, "committed_usd": 2200.0, **ok_auth},
            "access": {"depot": "DEP-NY", "climb_required": False, "access_hours": "Mon-Fri 8am-5pm, escort required"},
            "visit": {"planned_time": "15:30", "signal_note": "Good signal"},
            "alarms": [],
            "ml_scores": {"segment": "Backhaul Constrained", "outage_risk": 0.12, "next_best_action": "preventive",
                          "recommended_parts": [
                              {"sku": "FS-TRN-6101", "qty": 1, "confidence": 0.94, "reason": "Receive power at threshold"},
                              {"sku": "FS-FBR-7101", "qty": 1, "confidence": 0.87, "reason": "Patch cords past cleaning limit"},
                              {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.8, "reason": "Due on this visit"}],
                          "days_to_failure": {"FS-TRN-6101": 4, "FS-FBR-7101": 9, "FS-FBR-7110": 11},
                          "upgrade_skus": ["FS-TRN-6131"], "predicted_parts_cost_usd": 190.0},
        }))
        for a in self.area_rows(t2, 44):
            if a["visit"]["next_visit_date"] == d0:
                a["visit"]["next_visit_date"] = (self.d0 + dt.timedelta(days=1)).isoformat()
            rows.append(a)

        # 3. Sofia Alvarez - Dallas-Fort Worth, with a 12-node stadium-district small-cell cluster.
        sofia = {"tech_id": "T1003", "employee_id": "427190", "first_name": "Sofia", "last_name": "Alvarez",
                 "email": "sofia.alvarez@telco.example.com", "certifications": ["RF awareness", "Fiber splicing", "DC power"]}
        t3 = self.area("A-TX-DFW", 0, sofia)
        cluster = {"cluster_id": "CL-4471", "cluster_name": "Lone Star Stadium District", "sites": 12, "tier": "HUB",
                   "agreement_id": "VSA-CL-4471"}
        for n in range(12):
            on_route = n < 3
            ov = {"site_id": f"S001030{n + 1:02d}", "site_code": f"DFW-S{n + 401}",
                  "sla": {"tier": "HUB", "tier_name": "Hub", "restore_hours": 2, "pm_cadence_days": 30, "agreement_id": "VSA-CL-4471"},
                  "auth": {"budget_limit_usd": 5000.0, **ok_auth},
                  "access": {"depot": "DEP-SC", "climb_required": False}}
            if on_route:
                deep_update(ov, {"visit": {"planned_time": ["08:30", "10:15", "12:00"][n],
                                 "signal_note": ["Underground cable vault", "Good signal", "Rooftop plant room, weak LTE"][n]}})
            else:
                ov["visit"] = {"next_visit_date": (self.d0 + dt.timedelta(days=1 + n % 9)).isoformat()}
            if n == 0:
                ov["alarms"] = [self.alarm("transport", "minor", days_ago=1, pick=0)]
                ov["ml_scores"] = {"outage_risk": 0.31, "next_best_action": "corrective", "transport_failure_risk": 0.85,
                                   "recommended_parts": [
                                       {"sku": "FS-TRN-6105", "qty": 1, "confidence": 0.95, "reason": "Fronthaul receive power low"},
                                       {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.86, "reason": "Due on this visit"},
                                       {"sku": "FS-PWR-2310", "qty": 1, "confidence": 0.8, "reason": "Surge counter at end-of-life"}],
                                   "days_to_failure": {"FS-TRN-6105": 2, "FS-FBR-7110": 6, "FS-PWR-2310": 9},
                                   "upgrade_skus": ["FS-SIT-8130"], "predicted_parts_cost_usd": 300.0}
            rows.append(self.site(t3, "small_cell", name=f"Lone Star Stadium Node {n + 1:02d}", cluster=cluster, overrides=ov, due_today=on_route))
        rows.append(self.site(t3, "rooftop_site", name="Fort Worth Stockyards Rooftop", due_today=True, overrides={
            "site_id": "S00103020", "site_code": "DFW-0612",
            "address": {"street": "1200 W 7th St", "city": "Fort Worth", "state": "TX", "zip": "76102"},
            "sla": {"tier": "STANDARD", "tier_name": "Standard", "restore_hours": 24, "pm_cadence_days": 90, "agreement_id": "VSA-900147"},
            "auth": {"budget_limit_usd": 5000.0, "committed_usd": 1980.55, "hold_days": 68, "on_hold": True,
                     "hold_reason": "Landlord access dispute - roof lease renewal unsigned"},
            "access": {"depot": "DEP-SC", "climb_required": False, "notes": "Building management is refusing roof access"},
            "visit": {"planned_time": "13:30", "signal_note": "Good signal"},
            "alarms": [self.alarm("power", "minor", days_ago=9, pick=2)],
            "ml_scores": {"segment": "Chronic Alarm Sites", "outage_risk": 0.71, "next_best_action": "clear_access_hold",
                          "recommended_parts": [{"sku": "FS-PWR-2310", "qty": 1, "confidence": 0.9, "reason": "Past predicted end of life"},
                                                {"sku": "FS-PWR-2204", "qty": 2, "confidence": 0.86, "reason": "Health trend below threshold"}],
                          "days_to_failure": {"FS-PWR-2310": 0, "FS-PWR-2204": 5}, "upgrade_skus": [], "predicted_parts_cost_usd": 920.0},
        }))
        rows.append(self.site(t3, "central_office", name="Plano Central Office", due_today=True, overrides={
            "site_id": "S00103021", "site_code": "DFW-0004",
            "address": {"street": "3100 Independence Pkwy", "city": "Plano", "state": "TX", "zip": "75074"},
            "sla": {"tier": "CRITICAL", "tier_name": "Critical", "restore_hours": 4, "pm_cadence_days": 30, "agreement_id": "VSA-512240"},
            "auth": {"budget_limit_usd": 15000.0, "committed_usd": 1420.0, **ok_auth},
            "access": {"depot": "DEP-SC", "climb_required": False},
            "visit": {"planned_time": "15:00", "signal_note": "Good signal"},
            "alarms": [],
            "ml_scores": {"segment": "Stable Performers", "outage_risk": 0.05, "next_best_action": "preventive",
                          "recommended_parts": [{"sku": "FS-CLG-3101", "qty": 2, "confidence": 0.96, "reason": "Due on this visit"},
                                                {"sku": "FS-FBR-7110", "qty": 1, "confidence": 0.88, "reason": "Due on this visit"},
                                                {"sku": "FS-SIT-8150", "qty": 1, "confidence": 0.62, "reason": "Detector past service life"}],
                          "days_to_failure": {"FS-CLG-3101": 2, "FS-FBR-7110": 9, "FS-SIT-8150": 14},
                          "upgrade_skus": ["FS-CLG-3150"], "predicted_parts_cost_usd": 210.0},
        }))
        for a in self.area_rows(t3, 38):
            if a["visit"]["next_visit_date"] == d0:
                a["visit"]["next_visit_date"] = (self.d0 + dt.timedelta(days=1)).isoformat()
            rows.append(a)
        return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-date", default=dt.date.today().isoformat())
    ap.add_argument("--target-mb", type=float, default=100.0, help="approximate total size in MiB")
    ap.add_argument("--parts", type=int, default=4, help="number of part files (keep each under GitHub's 50MB warning)")
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "data", "databricks-dump"))
    args = ap.parse_args(argv)

    export_date = dt.date.fromisoformat(args.export_date)
    g = Gen(export_date, args.seed)
    target = int(args.target_mb * 1024 * 1024)
    per_part = target // args.parts + 1
    out_dir = os.path.abspath(os.path.join(args.out, f"dt={export_date.isoformat()}"))
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.startswith("part-") or f in ("_SUCCESS", "_manifest.json"):
            os.remove(os.path.join(out_dir, f))

    job_uuid = uuid.UUID(int=g.r.getrandbits(128))
    written, rows, areas = 0, 0, 3
    files = []
    pending = g.personas()
    base_codes = [c for c in C.AREAS if c not in ("A-BOS-NS", "A-NY-HV", "A-TX-DFW")] + list(C.AREAS)
    variant = {c: 0 for c in C.AREAS}
    for part in range(args.parts):
        name = f"part-{part:05d}-{job_uuid}-c000.json"
        path = os.path.join(out_dir, name)
        part_bytes, part_rows = 0, 0
        with open(path, "w", encoding="utf-8") as fh:
            while part_bytes < per_part and written < target:
                if not pending:
                    code = base_codes[areas % len(base_codes)]
                    variant[code] += 1
                    area = g.area(code, variant[code])
                    pending = list(g.area_rows(area, g.r.randint(45, 75)))
                    areas += 1
                line = json.dumps(pending.pop(0), separators=(",", ":"), ensure_ascii=False) + "\n"
                b = len(line.encode("utf-8"))
                fh.write(line)
                part_bytes += b
                written += b
                part_rows += 1
        rows += part_rows
        files.append({"file": name, "rows": part_rows, "bytes": part_bytes})
        print(f"  {name}  {part_rows:>7,} rows  {part_bytes / 1048576:6.1f} MiB", flush=True)

    manifest = {
        "table": "telco_prod.network360.site_asset_health_daily",
        "export_date": export_date.isoformat(), "schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION,
        "format": "jsonl", "rows": rows, "areas": areas, "bytes": written, "files": files,
        "generator": "databricks/generate_mock_dump.py", "seed": args.seed,
        "demo_techs": ["T1001", "T1002", "T1003"],
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    open(os.path.join(out_dir, "_SUCCESS"), "w").close()
    print(f"Wrote {rows:,} network sites ({areas:,} areas) = {written / 1048576:.1f} MiB to {out_dir}")


if __name__ == "__main__":
    main()
