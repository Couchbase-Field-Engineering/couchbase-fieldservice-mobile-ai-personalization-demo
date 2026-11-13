/**
 * Offline assistant: answers from what Couchbase Lite already holds.
 *
 *  1. this technician's earlier answers (`assistant` doc `answers`, keyed by site + normalized question)
 *  2. the site's work plan (`work_plans` doc) and site document (alarms, assets, budget, access, history)
 *  3. the site's context cache (`context_cache` docs the server assembled
 *     from the Couchbase Labs Agent Operations Manager Knowledge Base + tool facts)
 *  4. the runbook FAQ synced in the `catalog` doc
 *
 * Mirrors backend/app/assistant.py's intent keywords so the same question
 * lands on the same cached context offline as online.
 */
import type { Snapshot } from '../../db/localDb';
import { ids } from '../../db/localDb';
import type { ChatMessage, SuggestedAction } from '../../types';

const KEYWORDS: Record<string, string[]> = {
  budget: ['budget', 'override', 'over budget', 'limit', 'spend', 'authoriz', 'authoris', 'hold', 'approval', 'committed'],
  rma: ['rma', 'return', 'dead on arrival', 'doa', 'wrong part', 'faulty part', 'send back'],
  recurring: ['recurring', 'every week', 'every month', 'every quarter', 'cadence', 'interval', 'replace every', 'schedule a', 'on a schedule'],
  outage: ['outage window', 'window', 'off-air', 'off air', 'downtime', 'service affecting', 'service-affecting', 'noc', 'take down', 'lock the sector', 'power down'],
  parts: ['in stock', 'stock', 'available', 'availability', 'on hand', 'backorder', 'on order', 'substitute', 'part number', 'sku', 'how much', 'cost', 'price', 'depot', 'spare'],
  access: ['access', 'gate', 'key', 'escort', 'landlord', 'climb', 'hours', 'get in', 'lockbox', 'permit', 'directions'],
  alarms: ['alarm', 'alarms', 'fault', 'vswr', 'rectifier fail', 'high temp', 'temperature', 'link down', 'degraded', 'health', 'asset', 'why is'],
  history: ['history', 'last work order', 'last time', 'previous', 'replaced before', 'usually', 'how often', 'what was done', 'who was here'],
  visit: ['visit', 'stop', 'route', 'next time', 'come back', 'follow up', 'log'],
  workplan: ['work plan', 'plan', 'recommend', 'what should', 'what needs', 'needs doing', 'to do', 'checklist', 'preventive', 'corrective', 'predict',
    'about to fail', 'failing', 'fail', 'replace', 'battery', 'batteries', 'filter', 'today', 'job'],
};

export function classify(q: string): string {
  const m = q.toLowerCase();
  let best = 'general';
  let score = 0;
  for (const [intent, kws] of Object.entries(KEYWORDS)) {
    const s = kws.filter((k) => m.includes(k)).length;
    if (s > score) {
      best = intent;
      score = s;
    }
  }
  return best;
}

export const normalize = (q: string) => q.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim().slice(0, 120);
const money = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const short = (name: string) => name.split(',')[0];
/** A procedure question asked generically ("how do I…") is a runbook question even with a site open. */
const GENERIC = /^\s*(how|what is|what are|what's the|is|are|can|do|does|who|which|when do)\b/i;
const ABOUT_SITE = /\b(this|their|they|them|the site|this site|the tower|this tower|this cabinet|here|we|our|my)\b/i;

export function answerOffline(q: string, snap: Snapshot, siteId: string | null, techId: string): Omit<ChatMessage, 'id' | 'at' | 'role'> {
  const intent = classify(q);
  const prior = snap.chat?.answers?.[`${siteId ?? '-'}|${normalize(q)}`];
  if (prior) {
    return { text: prior.reply, intent, actions: prior.actions, offline: true, context: { status: 'device', latency_ms: 0 } };
  }
  const m = q.toLowerCase();
  const faq = (snap.catalog?.faq ?? [])
    .map((f) => ({ f, s: f.keywords.filter((k) => m.includes(k)).length }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)[0];

  const runbookOnly = GENERIC.test(q) && !ABOUT_SITE.test(q) && !!faq;
  const a = siteId && !runbookOnly ? snap.sites[siteId] : null;
  const plan = siteId && !runbookOnly ? snap.plans[siteId] : null;
  const ctx = siteId ? snap.contexts[ids.ctx(siteId, intent)] : snap.contexts[ids.ctx(techId, `runbook_${intent}`)];
  const actions: SuggestedAction[] = [];
  let text: string | null = null;
  const depot = a ? (snap.catalog?.depots[a.access.depot]?.name ?? a.access.depot) : '';

  if (a && plan && (intent === 'workplan' || intent === 'recurring')) {
    const sel = plan.lines.filter((l) => l.selected);
    const cm = plan.tasks.filter((t) => t.kind === 'corrective');
    const pm = plan.tasks.filter((t) => t.kind === 'preventive');
    const urgent = plan.lines.filter((l) => l.days_to_failure != null && l.days_to_failure <= 7);
    const low = plan.lines.filter((l) => l.on_hand_at_depot < l.qty);
    text = `From the plan on this phone - ${plan.work_type.toLowerCase()} at ${a.site_name}: `;
    text += cm.length ? `${cm.length} corrective task${cm.length > 1 ? 's' : ''} first, then the ${pm.length}-step checklist.` : `the ${pm.length}-step preventive checklist.`;
    if (sel.length) text += ` ${sel.length} recommended part line${sel.length > 1 ? 's' : ''}, ${money(plan.plan_total_usd)}.`;
    if (urgent.length) text += ` Start with ${urgent.slice(0, 2).map((l) => `${short(l.name)} x${l.qty} (~${Math.max(0, l.days_to_failure ?? 0)}d to failure)`).join(', ')}.`;
    if (low.length) text += ` The depot is short on ${low.slice(0, 2).map((l) => short(l.name)).join(', ')}.`;
    if (!plan.auth.ok && !plan.auth.on_hold) text += ` That is ${money(plan.auth.shortfall_usd)} over the remaining site budget - submit it as a budget override.`;
    if (plan.auth.on_hold) text += ' This site is on an access hold.';
    if (plan.service_affecting) text += ' Some of it is service-affecting: get an outage window from the NOC first.';
    actions.push({ label: 'Open Work order', screen: 'workorder', args: { site_id: a.site_id } });
  } else if (a && intent === 'alarms') {
    const al = a.alarms ?? [];
    text = al.length
      ? `${a.site_name} has ${al.length} open alarm${al.length > 1 ? 's' : ''}: ${al.slice(0, 3).map((x) => `${x.severity} - ${x.text}${x.action ? ` (${x.action})` : ''}`).join('; ')}.`
      : `${a.site_name} has no open alarms as of this morning's export.`;
    actions.push({ label: 'Open Work order', screen: 'workorder', args: { site_id: a.site_id } });
  } else if (a && plan && intent === 'outage') {
    const sa = plan.lines.filter((l) => l.service_affecting);
    const mins = sa.reduce((s, l) => s + l.swap_min * l.qty, 0);
    text = sa.length
      ? `Yes - ${sa.slice(0, 3).map((l) => short(l.name)).join(', ')} ${sa.length === 1 ? 'is' : 'are'} service-affecting, about ${mins} minutes. Request an outage window from the NOC; it will send when you have a connection. ${a.sla.tier_name} site, ${a.sla.restore_hours}h restore target.`
      : `Nothing on today's plan for ${a.site_name} is service-affecting, so no outage window is needed.`;
    if (sa.length) {
      actions.push({ label: `Request ${Math.max(15, Math.min(240, mins))}-min outage window`, tool: 'request_outage_window',
        args: { site_id: a.site_id, duration_min: Math.max(15, Math.min(240, mins)), reason: `Service-affecting swap: ${sa.slice(0, 3).map((l) => short(l.name)).join(', ')}` } });
    }
  } else if (a && intent === 'budget') {
    const c = a.auth;
    const avail = c.budget_limit_usd + (c.temporary_extension_usd ?? 0) - c.committed_usd;
    text = c.on_hold
      ? `${a.site_name} is on an access hold for ${c.hold_days} days: ${c.hold_reason}. No work order can be booked until the Site Access desk releases it.`
      : `${a.site_name} has ${money(avail)} left this quarter: a ${money(c.budget_limit_usd)} maintenance budget with ${money(c.committed_usd)} committed. Parts above that need a budget override approved by Field Ops.`;
  } else if (a && intent === 'history') {
    const lo = a.work_history[0];
    text = `${a.site_name}: ${money(a.maintenance.last_12mo_usd)} of parts over ${a.maintenance.work_orders_last_12mo} work orders in 12 months, average ${money(a.maintenance.avg_work_order_usd)}.` +
      (lo ? ` Last work order ${lo.work_order_id} on ${lo.date}: ${(lo.work_type ?? 'maintenance').toLowerCase()}, ${money(lo.total_usd)}.` : '');
    actions.push({ label: 'Open site', screen: 'site', args: { site_id: a.site_id } });
  } else if (a && intent === 'access') {
    const d = a.access;
    text = `${a.site_name}: access ${d.access_hours}, ${d.climb_required ? 'tower climb required (two climb-certified techs and a rescue kit)' : 'no climb required'}.` +
      (d.notes ? ` ${d.notes}.` : '') + ` Field note: ${a.visit.signal_note}.` + (a.auth.on_hold ? ` The site is on an access hold: ${a.auth.hold_reason}.` : '');
  } else if (a && intent === 'visit') {
    text = `Last visit ${a.visit.last_visit}; every ${a.visit.cadence_days} days, next ${a.visit.next_visit_date}.`;
    actions.push({ label: 'Log this visit', screen: 'visit', args: { site_id: a.site_id } });
  } else if (a && intent === 'parts') {
    const words = m.split(/\s+/).map((w) => w.replace(/[^a-z0-9+]/g, '')).filter((w) => w.length > 3 && !['stock', 'depot', 'there', 'have', 'many', 'much', 'cost', 'blocks', 'modules'].includes(w));
    const hit = (snap.catalog?.products ?? []).find((p) => words.some((w) => `${p.name} ${p.tags.join(' ')}`.toLowerCase().includes(w.replace(/ies$/, 'y').replace(/s$/, ''))));
    const line = hit ? plan?.lines.find((l) => l.sku === hit.sku) : null;
    if (hit) {
      text = `${hit.name} (${hit.sku}) is ${money(hit.unit_cost)} per ${hit.uom}.` +
        (line ? ` ${line.on_hand_at_depot} on hand at ${depot} as of the last sync.` : ` Depot stock for it isn't on this phone - it shows on the work order once you're connected.`) +
        (a.wear[hit.sku] ? ` Last replaced here ${a.wear[hit.sku].last_replaced}.` : '') +
        (hit.service_affecting ? ' Swapping it is service-affecting - get an outage window first.' : '');
    } else if (plan?.lines.length) {
      text = `Parts recommended for ${a.site_name}, with stock at ${depot}: ${plan.lines.slice(0, 4).map((l) => `${l.qty} x ${short(l.name)} (${l.on_hand_at_depot} on hand)`).join('; ')}.`;
    }
    actions.push({ label: 'Open Work order', screen: 'workorder', args: { site_id: a.site_id } });
  }
  if (!text && faq) text = faq.f.a;
  if (!text && ctx?.kb_runbook?.[0]) text = ctx.kb_runbook[0].answer ?? ctx.kb_runbook[0].content;
  if (!text && !siteId && intent !== 'general') {
    text = 'Open a stop on your route and ask again - offline, I answer from that site\'s data on this phone.';
    actions.push({ label: "Open today's route", screen: 'route' });
  }
  if (!text) {
    text = "You're offline right now, so I can only answer from what's saved on this phone: the site, its alarms, work plan, budget and history, and the runbook FAQ.";
  }
  return {
    text,
    intent,
    actions,
    offline: true,
    context: { status: ctx || plan ? 'device' : 'none', latency_ms: 0 },
    sources: faq && (runbookOnly || !a) ? [{ title: 'Field Maintenance Runbook (on device)', snippet: faq.f.q, kind: 'couchbase-lite' }] : [],
  };
}
