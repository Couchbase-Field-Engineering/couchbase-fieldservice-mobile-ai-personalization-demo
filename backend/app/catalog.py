"""Reference catalog for the demo: the spare parts a telecom field technician
fits at cell sites, exchanges and fiber cabinets, the site types and their
preventive-maintenance checklists, SLA classes, work types and the regional
spares depots that hold stock.

This is the single source of truth shared by the Databricks mock-dump
generator (databricks/generate_mock_dump.py imports it), the backend's
work-plan engine and the MCP tools. Part numbers, names and costs are
illustrative demo values, not any vendor's catalog.
"""
from __future__ import annotations

import hashlib

# --------------------------------------------------------------------------
# Part categories. `risk` names the asset-health model score that drives how
# strongly parts in the category are recommended for a site.
# --------------------------------------------------------------------------
CATEGORIES = {
    "power": {"name": "Power & batteries", "risk": "power_failure_risk"},
    "cooling": {"name": "Cooling & environment", "risk": "cooling_failure_risk"},
    "radio": {"name": "Radio & baseband", "risk": "radio_failure_risk"},
    "antenna": {"name": "Antenna & RF path", "risk": "antenna_failure_risk"},
    "transport": {"name": "Transport & optics", "risk": "transport_failure_risk"},
    "fiber": {"name": "Fiber & cabling", "risk": "fiber_failure_risk"},
    "site": {"name": "Site & safety", "risk": "site_failure_risk"},
    "tools": {"name": "Test & tools", "risk": "tooling_gap_score"},
}

# SKU, name, category, unit of measure, unit cost (USD), spec, tags, whether
# it is a life-limited wear item (replaced on a cadence), minutes to swap and
# whether swapping it takes service down.
PRODUCTS = [
    # power & batteries
    {"sku": "FS-PWR-2101", "name": "Rectifier Module, 48V 3kW, hot-swap", "category": "power", "uom": "each",
     "unit_cost": 1180.00, "spec": "48V DC, 3 kW", "tags": ["core", "rectifier", "dc power"], "wear_item": False, "swap_min": 15, "service_affecting": False},
    {"sku": "FS-PWR-2204", "name": "VRLA Battery Block, 12V 190Ah, front terminal", "category": "power", "uom": "each",
     "unit_cost": 412.00, "spec": "12V 190Ah", "tags": ["core", "battery", "backup"], "wear_item": True, "swap_min": 25, "service_affecting": False},
    {"sku": "FS-PWR-2260", "name": "Lithium Battery Module, 48V 100Ah, rack mount", "category": "power", "uom": "each",
     "unit_cost": 1640.00, "spec": "48V 100Ah LFP", "tags": ["battery", "lithium", "upgrade"], "wear_item": False, "swap_min": 30, "service_affecting": False},
    {"sku": "FS-PWR-2302", "name": "DC Circuit Breaker, 63A, plug-in", "category": "power", "uom": "each",
     "unit_cost": 38.00, "spec": "63A 80VDC", "tags": ["breaker", "dc power"], "wear_item": False, "swap_min": 10, "service_affecting": True},
    {"sku": "FS-PWR-2310", "name": "AC Surge Protection Device, Class II cartridge", "category": "power", "uom": "each",
     "unit_cost": 96.00, "spec": "40 kA, 320V", "tags": ["core", "surge", "lightning"], "wear_item": True, "swap_min": 10, "service_affecting": False},
    {"sku": "FS-PWR-2415", "name": "Generator Service Kit, oil, fuel and air filters", "category": "power", "uom": "kit",
     "unit_cost": 129.00, "spec": "20-30 kW diesel", "tags": ["core", "generator", "filter"], "wear_item": True, "swap_min": 45, "service_affecting": False},
    {"sku": "FS-PWR-2420", "name": "Generator Starter Battery, 12V", "category": "power", "uom": "each",
     "unit_cost": 148.00, "spec": "12V 850 CCA", "tags": ["generator", "battery"], "wear_item": True, "swap_min": 15, "service_affecting": False},
    # cooling & environment
    {"sku": "FS-CLG-3101", "name": "Shelter Air Filter, 20x25x2, 6-pack", "category": "cooling", "uom": "pack",
     "unit_cost": 54.00, "spec": "MERV 8, 6 filters", "tags": ["core", "filter", "hvac"], "wear_item": True, "swap_min": 10, "service_affecting": False},
    {"sku": "FS-CLG-3110", "name": "Cabinet DC Fan Tray, 48V", "category": "cooling", "uom": "each",
     "unit_cost": 236.00, "spec": "48V, 3 fans", "tags": ["core", "fan", "cabinet"], "wear_item": True, "swap_min": 15, "service_affecting": False},
    {"sku": "FS-CLG-3122", "name": "HVAC Contactor and Capacitor Kit", "category": "cooling", "uom": "kit",
     "unit_cost": 88.00, "spec": "2-ton wall-mount unit", "tags": ["hvac", "compressor"], "wear_item": True, "swap_min": 30, "service_affecting": False},
    {"sku": "FS-CLG-3140", "name": "Heat Exchanger Fan, 48V", "category": "cooling", "uom": "each",
     "unit_cost": 164.00, "spec": "48V, 225 mm", "tags": ["fan", "cabinet"], "wear_item": True, "swap_min": 20, "service_affecting": False},
    {"sku": "FS-CLG-3150", "name": "Temperature and Humidity Sensor", "category": "cooling", "uom": "each",
     "unit_cost": 42.00, "spec": "dry-contact + Modbus", "tags": ["sensor", "alarm"], "wear_item": False, "swap_min": 10, "service_affecting": False},
    # radio & baseband
    {"sku": "FS-RAN-4101", "name": "Remote Radio Unit, mid-band 4x40W", "category": "radio", "uom": "each",
     "unit_cost": 3900.00, "spec": "4T4R, 4x40W", "tags": ["rru", "radio", "sector"], "wear_item": False, "swap_min": 90, "service_affecting": True},
    {"sku": "FS-RAN-4120", "name": "Baseband Processing Card", "category": "radio", "uom": "each",
     "unit_cost": 2750.00, "spec": "LTE/NR, 6 cells", "tags": ["baseband", "bbu"], "wear_item": False, "swap_min": 40, "service_affecting": True},
    {"sku": "FS-RAN-4133", "name": "Radio Fan Module", "category": "radio", "uom": "each",
     "unit_cost": 210.00, "spec": "field replaceable", "tags": ["core", "fan", "rru"], "wear_item": True, "swap_min": 20, "service_affecting": False},
    {"sku": "FS-RAN-4150", "name": "GPS Timing Antenna Kit", "category": "radio", "uom": "kit",
     "unit_cost": 185.00, "spec": "antenna, arrestor, 10 m cable", "tags": ["gps", "timing", "sync"], "wear_item": False, "swap_min": 35, "service_affecting": False},
    # antenna & RF path
    {"sku": "FS-ANT-5101", "name": "Connector Weatherproofing Kit, 10 joints", "category": "antenna", "uom": "kit",
     "unit_cost": 46.00, "spec": "butyl + cold shrink", "tags": ["core", "weatherproof", "vswr"], "wear_item": True, "swap_min": 30, "service_affecting": False},
    {"sku": "FS-ANT-5110", "name": "RF Jumper, 1/2 in, 4.3-10, 3 m", "category": "antenna", "uom": "each",
     "unit_cost": 58.00, "spec": "low-PIM", "tags": ["core", "jumper", "vswr", "pim"], "wear_item": True, "swap_min": 25, "service_affecting": True},
    {"sku": "FS-ANT-5124", "name": "RET Actuator Motor", "category": "antenna", "uom": "each",
     "unit_cost": 320.00, "spec": "AISG 2.0", "tags": ["ret", "tilt"], "wear_item": False, "swap_min": 40, "service_affecting": False},
    {"sku": "FS-ANT-5130", "name": "AISG Control Cable, 10 m", "category": "antenna", "uom": "each",
     "unit_cost": 64.00, "spec": "8-pin, outdoor", "tags": ["ret", "aisg"], "wear_item": False, "swap_min": 20, "service_affecting": False},
    {"sku": "FS-ANT-5142", "name": "Coax Surge Arrestor, 4.3-10", "category": "antenna", "uom": "each",
     "unit_cost": 74.00, "spec": "gas tube, DC block", "tags": ["surge", "lightning"], "wear_item": True, "swap_min": 20, "service_affecting": True},
    # transport & optics
    {"sku": "FS-TRN-6101", "name": "SFP+ Optic, 10G LR, 10 km", "category": "transport", "uom": "each",
     "unit_cost": 88.00, "spec": "1310 nm, LC", "tags": ["core", "sfp", "optic", "backhaul"], "wear_item": True, "swap_min": 10, "service_affecting": True},
    {"sku": "FS-TRN-6105", "name": "SFP28 Optic, 25G LR, 10 km", "category": "transport", "uom": "each",
     "unit_cost": 165.00, "spec": "1310 nm, LC", "tags": ["sfp", "optic", "fronthaul"], "wear_item": True, "swap_min": 10, "service_affecting": True},
    {"sku": "FS-TRN-6120", "name": "Cell Site Router Fan Tray", "category": "transport", "uom": "each",
     "unit_cost": 240.00, "spec": "hot-swap", "tags": ["core", "fan", "router"], "wear_item": True, "swap_min": 10, "service_affecting": False},
    {"sku": "FS-TRN-6131", "name": "Cell Site Router Power Supply, DC", "category": "transport", "uom": "each",
     "unit_cost": 410.00, "spec": "48V, redundant", "tags": ["router", "power supply"], "wear_item": False, "swap_min": 15, "service_affecting": False},
    {"sku": "FS-TRN-6140", "name": "Microwave Outdoor Unit, 18 GHz", "category": "transport", "uom": "each",
     "unit_cost": 2150.00, "spec": "high band, 1+0", "tags": ["microwave", "odu", "backhaul"], "wear_item": False, "swap_min": 75, "service_affecting": True},
    {"sku": "FS-TRN-6152", "name": "Microwave IF Cable Kit, 30 m", "category": "transport", "uom": "kit",
     "unit_cost": 95.00, "spec": "connectors + grounding", "tags": ["microwave", "cable"], "wear_item": True, "swap_min": 60, "service_affecting": True},
    # fiber & cabling
    {"sku": "FS-FBR-7101", "name": "Fiber Patch Cord, LC/UPC single-mode, 3 m, 10-pack", "category": "fiber", "uom": "pack",
     "unit_cost": 49.00, "spec": "OS2 duplex", "tags": ["core", "patch", "fiber"], "wear_item": True, "swap_min": 10, "service_affecting": True},
    {"sku": "FS-FBR-7110", "name": "Fiber Cleaning Kit, one-click and wipes", "category": "fiber", "uom": "kit",
     "unit_cost": 39.00, "spec": "LC/SC, 800 cleans", "tags": ["core", "cleaning", "fiber"], "wear_item": True, "swap_min": 5, "service_affecting": False},
    {"sku": "FS-FBR-7122", "name": "Splice Protection Sleeves, 60 mm, 100-pack", "category": "fiber", "uom": "pack",
     "unit_cost": 18.00, "spec": "heat shrink", "tags": ["splice", "fiber"], "wear_item": True, "swap_min": 5, "service_affecting": False},
    {"sku": "FS-FBR-7130", "name": "OLT PON Optic, GPON C+", "category": "fiber", "uom": "each",
     "unit_cost": 129.00, "spec": "SFP, 1490/1310 nm", "tags": ["olt", "pon", "optic"], "wear_item": True, "swap_min": 10, "service_affecting": True},
    {"sku": "FS-FBR-7141", "name": "Fiber Splice Closure, 24-fiber", "category": "fiber", "uom": "each",
     "unit_cost": 112.00, "spec": "dome, IP68", "tags": ["closure", "splice"], "wear_item": False, "swap_min": 90, "service_affecting": True},
    {"sku": "FS-FBR-7150", "name": "Optical Network Terminal, GPON indoor", "category": "fiber", "uom": "each",
     "unit_cost": 68.00, "spec": "4 GE + Wi-Fi", "tags": ["ont", "customer"], "wear_item": False, "swap_min": 20, "service_affecting": True},
    # site & safety
    {"sku": "FS-SIT-8101", "name": "Obstruction Light, LED red, L-810", "category": "site", "uom": "each",
     "unit_cost": 198.00, "spec": "48V DC, steady burn", "tags": ["core", "tower light", "aviation"], "wear_item": True, "swap_min": 45, "service_affecting": False},
    {"sku": "FS-SIT-8110", "name": "Door Intrusion Sensor", "category": "site", "uom": "each",
     "unit_cost": 34.00, "spec": "magnetic, dry contact", "tags": ["alarm", "security"], "wear_item": False, "swap_min": 15, "service_affecting": False},
    {"sku": "FS-SIT-8121", "name": "Coax Grounding Kit, 1/2 in, 10-pack", "category": "site", "uom": "pack",
     "unit_cost": 62.00, "spec": "pre-formed, 1.5 m lead", "tags": ["core", "grounding", "lightning"], "wear_item": True, "swap_min": 40, "service_affecting": False},
    {"sku": "FS-SIT-8130", "name": "Site Padlock, keyed alike", "category": "site", "uom": "each",
     "unit_cost": 27.00, "spec": "weatherproof", "tags": ["security", "access"], "wear_item": False, "swap_min": 5, "service_affecting": False},
    {"sku": "FS-SIT-8144", "name": "Fire Extinguisher, CO2, 5 lb", "category": "site", "uom": "each",
     "unit_cost": 89.00, "spec": "electrical rated", "tags": ["safety", "compliance"], "wear_item": True, "swap_min": 5, "service_affecting": False},
    {"sku": "FS-SIT-8150", "name": "Shelter Smoke Detector", "category": "site", "uom": "each",
     "unit_cost": 48.00, "spec": "photoelectric, relay out", "tags": ["safety", "alarm"], "wear_item": True, "swap_min": 15, "service_affecting": False},
    {"sku": "FS-SIT-8162", "name": "UV Cable Ties and Label Kit", "category": "site", "uom": "kit",
     "unit_cost": 14.00, "spec": "100 ties + labels", "tags": ["core", "cable management"], "wear_item": True, "swap_min": 5, "service_affecting": False},
    # test & tools
    {"sku": "FS-TLS-9101", "name": "PIM Test Load and Adapter Kit", "category": "tools", "uom": "kit",
     "unit_cost": 540.00, "spec": "4.3-10 / 7-16", "tags": ["pim", "test"], "wear_item": False, "swap_min": 0, "service_affecting": False},
    {"sku": "FS-TLS-9110", "name": "Torque Wrench, 4.3-10 connectors", "category": "tools", "uom": "each",
     "unit_cost": 129.00, "spec": "5 N·m preset", "tags": ["tool", "connector"], "wear_item": False, "swap_min": 0, "service_affecting": False},
]
PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}

# What each kind of site wears out: sku -> typical replacements per year.
# The generator derives wear and work history from this, with noise. `pm`
# is the preventive-maintenance checklist a technician works through on a
# routine visit; `assets` is the installed equipment the site doc lists.
SITE_TYPES = {
    "macro_tower": {"name": "Macro cell tower", "wear": {
        "FS-PWR-2204": 1.0, "FS-CLG-3101": 4, "FS-ANT-5101": 2, "FS-ANT-5110": 1, "FS-TRN-6101": 0.6, "FS-SIT-8101": 0.5,
        "FS-PWR-2415": 2, "FS-SIT-8121": 0.5, "FS-RAN-4133": 0.6, "FS-FBR-7110": 2, "FS-PWR-2310": 0.5, "FS-SIT-8162": 2},
        "pm": ["Battery string float voltage and conductance test", "Rectifier load share and alarm check",
               "Shelter HVAC filter and coil inspection", "RF connector torque and weatherproofing inspection",
               "Tower lighting and grounding inspection", "Generator run test and fuel level"],
        "assets": [("power", "DC power plant, 48V"), ("power", "Battery string A"), ("power", "Standby generator"),
                   ("cooling", "Shelter HVAC"), ("radio", "Baseband unit"), ("radio", "Sector radios (3)"),
                   ("antenna", "Antenna line, 3 sectors"), ("transport", "Cell site router")]},
    "rooftop_site": {"name": "Rooftop cell site", "wear": {
        "FS-PWR-2204": 0.8, "FS-CLG-3110": 1, "FS-ANT-5101": 2, "FS-ANT-5110": 1, "FS-TRN-6101": 0.6, "FS-RAN-4133": 0.8,
        "FS-FBR-7110": 2, "FS-PWR-2310": 0.5, "FS-SIT-8121": 0.4, "FS-SIT-8162": 2, "FS-ANT-5142": 0.4},
        "pm": ["Battery cabinet voltage and temperature check", "Cabinet fan and heat exchanger inspection",
               "RF connector torque and weatherproofing inspection", "Roof penetration, ballast and cable tray inspection",
               "Lightning protection and bonding check"],
        "assets": [("power", "Outdoor power cabinet"), ("power", "Battery cabinet"), ("cooling", "Cabinet heat exchanger"),
                   ("radio", "Baseband unit"), ("radio", "Sector radios (3)"), ("antenna", "Antenna line, 3 sectors"),
                   ("transport", "Cell site router")]},
    "small_cell": {"name": "Small cell node", "wear": {
        "FS-TRN-6105": 0.6, "FS-FBR-7101": 0.5, "FS-FBR-7110": 2, "FS-PWR-2310": 0.6, "FS-SIT-8162": 1.5, "FS-ANT-5101": 1,
        "FS-PWR-2302": 0.3, "FS-SIT-8130": 0.5},
        "pm": ["Pole or strand mount and shroud inspection", "Fronthaul optic power levels", "Power meter and disconnect check",
               "RF exposure signage and labels"],
        "assets": [("radio", "Integrated radio node"), ("transport", "Fronthaul fiber"), ("power", "Pole power disconnect")]},
    "central_office": {"name": "Central office", "wear": {
        "FS-PWR-2204": 2, "FS-PWR-2101": 0.4, "FS-CLG-3101": 6, "FS-CLG-3122": 1, "FS-TRN-6101": 2, "FS-FBR-7101": 3,
        "FS-FBR-7110": 4, "FS-SIT-8144": 1, "FS-SIT-8150": 0.5, "FS-TRN-6120": 0.8, "FS-PWR-2415": 2, "FS-PWR-2420": 0.4},
        "pm": ["DC plant battery discharge test", "Rectifier shelf N+1 verification", "CRAC unit filter and condensate check",
               "Fiber distribution frame cleaning and label audit", "Fire suppression and smoke detector test",
               "Generator run test under load"],
        "assets": [("power", "DC power plant, 48V"), ("power", "Battery strings A/B"), ("power", "Standby generator"),
                   ("cooling", "CRAC units (2)"), ("transport", "Aggregation router"), ("fiber", "Fiber distribution frame")]},
    "fiber_hub": {"name": "Fiber hub cabinet", "wear": {
        "FS-FBR-7130": 1.2, "FS-FBR-7101": 2, "FS-FBR-7110": 4, "FS-FBR-7122": 1, "FS-CLG-3110": 1, "FS-PWR-2204": 0.8,
        "FS-CLG-3140": 0.6, "FS-SIT-8110": 0.3, "FS-SIT-8162": 2, "FS-PWR-2310": 0.5},
        "pm": ["OLT PON port optical power check", "Cabinet fan, filter and door seal inspection",
               "Battery backup runtime test", "Splitter and patch field cleaning", "Cabinet lock and intrusion alarm test"],
        "assets": [("fiber", "OLT shelf"), ("fiber", "Splitter and patch field"), ("power", "Cabinet power and battery"),
                   ("cooling", "Cabinet heat exchanger")]},
    "microwave_relay": {"name": "Microwave relay site", "wear": {
        "FS-TRN-6152": 0.6, "FS-PWR-2204": 1, "FS-PWR-2415": 2, "FS-PWR-2420": 0.5, "FS-SIT-8101": 0.6, "FS-SIT-8121": 0.5,
        "FS-CLG-3101": 3, "FS-ANT-5101": 1.5, "FS-PWR-2310": 0.8, "FS-SIT-8162": 1},
        "pm": ["Microwave link receive level and alignment check", "IF cable, connectors and grounding inspection",
               "Battery string and generator run test", "Tower lighting inspection", "Shelter HVAC filter change"],
        "assets": [("transport", "Microwave link A (ODU + dish)"), ("transport", "Microwave link B (ODU + dish)"),
                   ("power", "DC power plant, 48V"), ("power", "Standby generator"), ("cooling", "Shelter HVAC")]},
    "edge_pop": {"name": "Edge data center", "wear": {
        "FS-TRN-6105": 2, "FS-TRN-6101": 2, "FS-FBR-7101": 4, "FS-FBR-7110": 4, "FS-CLG-3101": 6, "FS-TRN-6120": 1,
        "FS-PWR-2101": 0.5, "FS-SIT-8144": 1, "FS-SIT-8150": 0.5, "FS-PWR-2204": 2},
        "pm": ["Core router fan tray and power supply check", "Optic receive power audit", "UPS and DC plant test",
               "Hot aisle temperature and filter check", "Fire suppression and access log review"],
        "assets": [("transport", "Core routers (2)"), ("power", "DC power plant and UPS"), ("cooling", "In-row cooling"),
                   ("fiber", "Meet-me fiber panel")]},
    "enterprise_cpe": {"name": "Enterprise customer premises", "wear": {
        "FS-FBR-7150": 0.4, "FS-TRN-6101": 0.5, "FS-FBR-7101": 1, "FS-FBR-7110": 1, "FS-PWR-2310": 0.3, "FS-TRN-6131": 0.2,
        "FS-SIT-8162": 1},
        "pm": ["Customer edge router health and optics check", "Demarcation panel cleaning and labelling",
               "UPS battery test", "Circuit loopback and throughput test"],
        "assets": [("transport", "Customer edge router"), ("fiber", "Demarcation panel"), ("power", "Rack UPS")]},
    "das_venue": {"name": "In-building DAS venue", "wear": {
        "FS-RAN-4133": 1, "FS-TRN-6105": 1.5, "FS-FBR-7101": 2, "FS-FBR-7110": 3, "FS-ANT-5110": 1.5, "FS-CLG-3110": 1,
        "FS-PWR-2204": 1, "FS-SIT-8162": 2, "FS-PWR-2302": 0.4},
        "pm": ["DAS head-end alarm and optical power check", "Remote unit status walk", "PIM and uplink noise sweep",
               "Head-end room cooling and battery check", "Venue access and escort coordination"],
        "assets": [("radio", "DAS head-end"), ("radio", "Remote radio units"), ("fiber", "Fiber distribution"),
                   ("power", "Head-end power and battery"), ("cooling", "Head-end room cooling")]},
}

# --------------------------------------------------------------------------
# SLA classes: how fast service has to be restored at a site, and so how a
# work order on it is prioritised.
# --------------------------------------------------------------------------
SLA_TIERS = [
    {"code": "STANDARD", "name": "Standard", "restore_hours": 24, "pm_cadence_days": 90,
     "blurb": "Single-site coverage with neighbours overlapping. Restore within 24 hours, preventive visit every quarter."},
    {"code": "PRIORITY", "name": "Priority", "restore_hours": 8, "pm_cadence_days": 60,
     "blurb": "High-traffic or enterprise-serving site. Restore within 8 hours, preventive visit every two months."},
    {"code": "CRITICAL", "name": "Critical", "restore_hours": 4, "pm_cadence_days": 30,
     "blurb": "Public-safety, hospital or sole-coverage site. Restore within 4 hours, monthly preventive visit."},
    {"code": "HUB", "name": "Hub", "restore_hours": 2, "pm_cadence_days": 30,
     "blurb": "Aggregation hub carrying a cluster of downstream sites. Restore within 2 hours; every site in the cluster "
              "shares the hub's priority."},
]
TIER_BY_CODE = {t["code"]: t for t in SLA_TIERS}

WORK_TYPES = ["Preventive maintenance", "Corrective maintenance", "Emergency repair", "Upgrade"]

# Regional spares depots and the states they serve. Stock is held per depot.
DEPOTS = {
    "DEP-NE": {"name": "Northeast Spares Depot", "city": "Putnam, CT", "states": ["MA", "NH", "ME", "VT", "CT", "RI"]},
    "DEP-NY": {"name": "Hudson Valley Spares Depot", "city": "Montgomery, NY", "states": ["NY", "NJ", "PA"]},
    "DEP-MA": {"name": "Mid-Atlantic Spares Depot", "city": "Hagerstown, MD", "states": ["MD", "VA", "DE", "DC", "WV", "NC"]},
    "DEP-SE": {"name": "Southeast Spares Depot", "city": "Lakeland, FL", "states": ["FL", "GA", "SC", "AL", "TN"]},
    "DEP-SC": {"name": "South Central Spares Depot", "city": "Arlington, TX", "states": ["TX", "OK", "LA", "AR", "NM"]},
    "DEP-MW": {"name": "Midwest Spares Depot", "city": "Terre Haute, IN", "states": ["IL", "IN", "OH", "MI", "WI", "MN", "MO", "KY"]},
    "DEP-W": {"name": "West Spares Depot", "city": "Ontario, CA", "states": ["CA", "AZ", "NV", "OR", "WA", "CO", "UT"]},
}
STATE_TO_DEPOT = {st: dep for dep, d in DEPOTS.items() for st in d["states"]}

AREAS = {
    "A-BOS-NS": {"name": "Boston North Shore", "state": "MA", "cities": [("Salem", "MA", "01970"), ("Beverly", "MA", "01915"),
                 ("Gloucester", "MA", "01930"), ("Peabody", "MA", "01960"), ("Danvers", "MA", "01923"), ("Lynn", "MA", "01901"),
                 ("Marblehead", "MA", "01945"), ("Newburyport", "MA", "01950"), ("Ipswich", "MA", "01938")]},
    "A-NY-HV": {"name": "Hudson Valley", "state": "NY", "cities": [("Kingston", "NY", "12401"), ("Rhinebeck", "NY", "12572"),
                ("Catskill", "NY", "12414"), ("New Paltz", "NY", "12561"), ("Poughkeepsie", "NY", "12601"), ("Hudson", "NY", "12534"),
                ("Saugerties", "NY", "12477"), ("Woodstock", "NY", "12498")]},
    "A-TX-DFW": {"name": "Dallas-Fort Worth", "state": "TX", "cities": [("Dallas", "TX", "75201"), ("Fort Worth", "TX", "76102"),
                 ("Arlington", "TX", "76010"), ("Plano", "TX", "75074"), ("Irving", "TX", "75060"), ("Denton", "TX", "76201"),
                 ("Garland", "TX", "75040"), ("McKinney", "TX", "75069")]},
    "A-PA-PHL": {"name": "Philadelphia Suburbs", "state": "PA", "cities": [("King of Prussia", "PA", "19406"), ("Media", "PA", "19063"),
                 ("West Chester", "PA", "19380"), ("Doylestown", "PA", "18901"), ("Norristown", "PA", "19401")]},
    "A-FL-TPA": {"name": "Tampa Bay", "state": "FL", "cities": [("Tampa", "FL", "33602"), ("St. Petersburg", "FL", "33701"),
                 ("Clearwater", "FL", "33755"), ("Brandon", "FL", "33511"), ("Lakeland", "FL", "33801")]},
    "A-OH-COL": {"name": "Central Ohio", "state": "OH", "cities": [("Columbus", "OH", "43215"), ("Dublin", "OH", "43017"),
                 ("Westerville", "OH", "43081"), ("Newark", "OH", "43055"), ("Lancaster", "OH", "43130")]},
    "A-CA-SAC": {"name": "Sacramento Valley", "state": "CA", "cities": [("Sacramento", "CA", "95814"), ("Roseville", "CA", "95678"),
                 ("Davis", "CA", "95616"), ("Elk Grove", "CA", "95624"), ("Folsom", "CA", "95630")]},
    "A-NC-RDU": {"name": "Raleigh-Durham", "state": "NC", "cities": [("Raleigh", "NC", "27601"), ("Durham", "NC", "27701"),
                 ("Cary", "NC", "27511"), ("Chapel Hill", "NC", "27514"), ("Apex", "NC", "27502")]},
}

# Why a technician has no signal at a site - the field reality the app is
# built for. Often the site they are standing at *is* the coverage.
SIGNAL_NOTES = ["Steel equipment shelter - no signal inside", "Site off-air - this tower is the local coverage",
                "Basement telecom room - no signal", "Mountaintop relay - dead zone on the access road",
                "Underground cable vault", "Rooftop plant room, weak LTE",
                "Good signal", "Good signal", "Good signal"]


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def part_cost(sku: str) -> float:
    """Unit cost charged to a site's maintenance budget for one part."""
    return PRODUCT_BY_SKU[sku]["unit_cost"]


def initial_inventory(depot: str) -> dict:
    """Deterministic on-hand units per SKU at a spares depot. A few SKUs are
    deliberately short so part shortages and follow-up visits show up."""
    out = {}
    for p in PRODUCTS:
        base = 24 if p["wear_item"] else 8
        out[p["sku"]] = base + _h(depot, p["sku"]) % (base * 4)
    # Hero shortages: rectifier modules are tight everywhere, battery blocks
    # are tight at the Northeast depot.
    out["FS-PWR-2101"] = 1 + _h(depot, "short") % 3
    if depot == "DEP-NE":
        out["FS-PWR-2204"] = 3
    return out


def depot_for_state(state: str) -> str:
    return STATE_TO_DEPOT.get(state, "DEP-MW")


def public_catalog() -> dict:
    """What the mobile app syncs as the `catalog` document."""
    return {
        "categories": {k: v["name"] for k, v in CATEGORIES.items()},
        "products": PRODUCTS,
        "sla_tiers": SLA_TIERS,
        "work_types": WORK_TYPES,
        "depots": {k: {"name": v["name"], "city": v["city"]} for k, v in DEPOTS.items()},
        "site_types": {k: v["name"] for k, v in SITE_TYPES.items()},
        "pm_checklists": {k: v["pm"] for k, v in SITE_TYPES.items()},
    }
