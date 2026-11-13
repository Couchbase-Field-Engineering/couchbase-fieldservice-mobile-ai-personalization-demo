/** Document shapes replicated from Couchbase (scope `field`) into Couchbase Lite. */

export type Contact = { name: string; role: string; phone: string; email?: string };

export type PartLine = {
  sku: string;
  name: string;
  qty: number;
  unit_cost: number;
  line_total: number;
  category?: string;
  uom?: string;
  swap_min?: number;
  service_affecting?: boolean;
  issued_qty?: number;
  backordered_qty?: number;
};

export type HistoryWorkOrder = {
  work_order_id: string;
  date: string;
  status: string;
  source: string;
  work_type?: string;
  follow_up_date?: string | null;
  line_count: number;
  lines: PartLine[];
  parts_usd?: number;
  total_usd: number;
  tasks_done?: string[];
  backordered?: { sku: string; name: string; qty: number; eta?: string }[];
  budget_override?: boolean;
  ticket?: string;
};

export type Alarm = {
  alarm_id: string;
  severity: 'critical' | 'major' | 'minor';
  code: string;
  text: string;
  action?: string;
  category: string;
  raised_at: string;
};

export type Asset = {
  asset_id: string;
  category: string;
  name: string;
  vendor?: string;
  installed?: string;
  health: number;
  status: 'ok' | 'degraded' | 'alarm';
};

export type Site = {
  type: 'site';
  site_id: string;
  export_date: string;
  rev: number;
  site_name: string;
  site_code: string;
  site_type: string;
  site_type_name: string;
  cluster: { cluster_id: string; cluster_name: string; sites: number } | null;
  address: { street: string; city: string; state: string; zip: string };
  area_id: string;
  area_name: string;
  contacts: Contact[];
  sla: { tier: string; tier_name: string; restore_hours: number; pm_cadence_days?: number; agreement_id: string; renewal_date: string; on_air_since?: string };
  auth: { budget_limit_usd: number; committed_usd: number; period?: string; hold_days: number; on_hold: boolean; hold_reason?: string | null; temporary_extension_usd?: number };
  access: { access_hours: string; climb_required: boolean; notes: string; depot: string };
  visit: { last_visit: string; cadence_days: number; next_visit_date: string; planned_time: string; signal_note: string; notes: string; last_outcome?: string };
  assets: Asset[];
  alarms: Alarm[];
  kpis: { availability_30d_pct: number; outage_min_30d: number; subscribers_served: number };
  work_history: HistoryWorkOrder[];
  wear: Record<string, { per_year: number; last_replaced: string; last_qty?: number | null }>;
  maintenance: { last_12mo_usd: number; ytd_usd: number; avg_work_order_usd: number; work_orders_last_12mo: number; category_mix: Record<string, number> };
  recurring_tasks: { sku: string; name: string; qty: number; unit_cost: number; cadence_weeks: number; next_date: string }[];
  rmas?: { rma_id: string; work_order_id: string; sku: string; name: string; qty: number; refund_usd: number; date: string }[];
  outage_windows?: { window_id: string; duration_min: number; reason: string; date: string }[];
  ml_scores: Record<string, unknown> & {
    model_version: string;
    segment: string;
    next_best_action: string;
    outage_risk: number;
    predicted_parts_cost_usd: number;
    recommended_parts: { sku: string; qty: number; confidence: number; reason: string }[];
    upgrade_skus: string[];
    days_to_failure: Record<string, number>;
  };
  flags: { generator_backup: boolean; shared_site: boolean };
};

export type PlanLine = {
  sku: string;
  name: string;
  category: string;
  category_name: string;
  uom: string;
  spec: string;
  qty: number;
  unit_cost: number;
  line_total: number;
  confidence: number | null;
  reason: string;
  on_hand_at_depot: number;
  availability: 'in_stock' | 'low' | 'backorder';
  days_to_failure: number | null;
  swap_min: number;
  service_affecting: boolean;
  score: number;
  selected: boolean;
  rank: number;
};

export type PlanTask = {
  id: string;
  kind: 'corrective' | 'preventive';
  title: string;
  est_min: number;
  severity?: string;
  alarm?: string;
};

export type AuthCheck = {
  budget_limit_usd: number;
  committed_usd: number;
  temporary_extension_usd: number;
  available_usd: number;
  on_hold: boolean;
  hold_days: number;
  hold_reason?: string | null;
  ok: boolean;
  shortfall_usd: number;
};

export type WorkPlanDoc = {
  type: 'work_plan';
  site_id: string;
  site_name: string;
  lines: PlanLine[];
  upgrades: { sku: string; name: string; category: string; uom: string; spec: string; qty: number; unit_cost: number; line_total: number; reason: string; on_hand_at_depot: number }[];
  tasks: PlanTask[];
  work_type: string;
  alarms: Alarm[];
  plan_total_usd: number;
  est_minutes: number;
  service_affecting: boolean;
  auth: AuthCheck;
  briefing: string[];
  model_version: string;
  segment: string;
  outage_risk?: number;
  export_date: string;
  site_rev: number;
  generated_at: string;
};

export type RouteStop = {
  site_id: string;
  site_name: string;
  site_code?: string;
  site_type: string;
  address: Site['address'];
  planned_time: string;
  signal_note: string;
  contact: string | null;
  plan_total_usd: number | null;
  tier: string;
  work_type?: string | null;
  alarm_count?: number;
  worst_alarm?: string | null;
  outage_risk?: number | null;
  last_work_date: string | null;
  hold_flag: boolean;
  status: 'planned' | 'visited';
  outcome?: string;
  visited_at?: string;
};

export type Tech = {
  type: 'tech';
  tech_id: string;
  employee_id: string;
  first_name: string;
  last_name: string;
  email: string;
  certifications?: string[];
  area_id: string;
  area_name: string;
  site_count: number;
  route_date: string;
  route: RouteStop[];
  due_this_week: number;
  committed_usd: number;
  on_hold_sites: number;
  open_alarms?: number;
  rev: number;
  export_date: string;
};

export type RequestStatus = 'pending' | 'processing' | 'awaiting_approval' | 'completed' | 'parts_pending' | 'failed';

/** An offline-first work order or field action: created on the phone, processed by the backend through AOM. */
export type WorkOrderRequest = {
  _id: string;
  type: 'request';
  tech_id: string;
  site_id: string;
  site_name?: string;
  tool: string;
  args: Record<string, unknown>;
  title: string;
  status: RequestStatus;
  created_at: string;
  summary?: string;
  cost_usd?: number;
  reason_code?: string | null;
  auth?: AuthCheck | null;
  item?: Record<string, unknown> & { work_order_id?: string; backordered?: HistoryWorkOrder['backordered']; follow_up_date?: string | null };
  governed?: boolean;
  trace_id?: string | null;
  approval_id?: string | null;
  completed_at?: string | null;
  _local?: boolean; // created on this device, not yet acknowledged by the server
};

export type ChatMessage = {
  id: string;
  role: 'tech' | 'assistant';
  text: string;
  at: string;
  site_id?: string | null;
  intent?: string;
  actions?: SuggestedAction[];
  context?: { status: string; latency_ms: number; kb_mode?: string; build_ms?: number };
  llm?: { status: string; namespace?: string; similarity?: number | null; latency_ms?: number | null; stub?: boolean; composed_locally?: boolean };
  sources?: { title: string; snippet: string; kind: string }[];
  offline?: boolean;
  pending?: boolean;
};

export type SuggestedAction = { label: string; tool?: string; screen?: string; args?: Record<string, unknown> };

export type ChatDoc = {
  type: 'assistant';
  messages: ChatMessage[];
  answers: Record<string, { reply: string; intent: string; at: string; actions?: SuggestedAction[] }>;
};

export type ContextDoc = {
  type: 'context_cache';
  scope: string;
  site_id: string | null;
  intent: string;
  personal: boolean;
  export_date: string;
  built_at: string;
  build_ms: number;
  kb_mode: string;
  kb_profile: { title: string; content: string }[];
  kb_runbook: { title: string; content: string; answer?: string }[];
  facts: { tool?: string; data?: any; catalog?: any[] };
};

export type Product = {
  sku: string;
  name: string;
  category: string;
  uom: string;
  unit_cost: number;
  spec: string;
  tags: string[];
  wear_item: boolean;
  swap_min: number;
  service_affecting: boolean;
};

export type Catalog = {
  type: 'catalog';
  export_date: string;
  categories: Record<string, string>;
  products: Product[];
  sla_tiers: { code: string; name: string; restore_hours: number; pm_cadence_days: number; blurb: string }[];
  work_types: string[];
  depots: Record<string, { name: string; city: string }>;
  site_types: Record<string, string>;
  pm_checklists: Record<string, string[]>;
  faq: { q: string; a: string; keywords: string[] }[];
};

export type SyncState = {
  engine: 'couchbase-lite' | 'preview';
  status: 'connecting' | 'connected' | 'idle' | 'busy' | 'offline' | 'paused' | 'error' | 'stopped';
  lastSyncAt: number | null;
  pendingPush: number;
  detail?: string;
  endpoint?: string;
};
