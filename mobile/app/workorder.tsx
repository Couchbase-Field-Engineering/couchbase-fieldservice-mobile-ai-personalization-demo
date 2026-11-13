import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { PlanLine, PlanTask, Product } from '@/src/types';
import { ChoiceRow } from '@/src/ui/Choice';
import { Button, Card, Empty, money2, Pill, SectionTitle, SEVERITY_TONE } from '@/src/ui/components';
import { openAction } from '@/src/ui/nav';
import { WorkOrderTracker } from '@/src/ui/WorkOrderTracker';

type Line = {
  sku: string; name: string; uom: string; qty: number; unit_cost: number; on_hand: number | null;
  swap_min: number; service_affecting: boolean; reason?: string; days_to_failure?: number | null;
};

/**
 * The work order: corrective tasks from the site's open alarms, the
 * preventive checklist, and the parts to fit - all read from Couchbase Lite
 * and costed on the phone, so it works inside a shelter with no signal.
 */
export default function WorkOrderScreen() {
  const { site_id = '' } = useLocalSearchParams<{ site_id: string }>();
  const { snap, request, offline } = useData();
  const a = snap.sites[site_id];
  const plan = snap.plans[site_id];
  const cat = snap.catalog;
  const [lines, setLines] = useState<Line[]>(() =>
    (plan?.lines ?? []).filter((l: PlanLine) => l.selected).map((l) => ({
      sku: l.sku, name: l.name, uom: l.uom, qty: l.qty, unit_cost: l.unit_cost, on_hand: l.on_hand_at_depot,
      swap_min: l.swap_min, service_affecting: l.service_affecting, reason: l.reason, days_to_failure: l.days_to_failure,
    })),
  );
  const tasks: PlanTask[] = plan?.tasks ?? [];
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [ticket, setTicket] = useState('');
  const [notes, setNotes] = useState('');
  const [workType, setWorkType] = useState<string>(plan?.work_type ?? 'Preventive maintenance');
  const [q, setQ] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  const [overrideReason, setOverrideReason] = useState('Predicted failure inside the SLA window; parts exceed the remaining site budget');

  const results = useMemo(() => {
    const m = q.trim().toLowerCase();
    if (!m || !cat) return [] as Product[];
    return cat.products.filter((p) => `${p.name} ${p.sku} ${p.tags.join(' ')} ${cat.categories[p.category]}`.toLowerCase().includes(m)).slice(0, 6);
  }, [q, cat]);

  if (!a) return <Empty icon="construct-outline" title="Site not on this phone" body="Open a stop from your route first." />;

  const costed = lines.map((l) => ({ ...l, total: Math.round(l.unit_cost * l.qty * 100) / 100 }));
  const total = Math.round(costed.reduce((s, l) => s + l.total, 0) * 100) / 100;
  const c = a.auth;
  const available = Math.round((c.budget_limit_usd + (c.temporary_extension_usd ?? 0) - c.committed_usd) * 100) / 100;
  const shortfall = Math.max(0, Math.round((total - available) * 100) / 100);
  const overBudget = total > available && !c.on_hold;
  const short = costed.filter((l) => l.on_hand != null && l.on_hand < l.qty);
  const affecting = costed.filter((l) => l.service_affecting);
  const outageMin = Math.max(15, Math.min(240, affecting.reduce((s, l) => s + l.swap_min * l.qty, 0)));
  const doneCount = tasks.filter((t) => done[t.id]).length;
  const estMin = tasks.reduce((s, t) => s + t.est_min, 0) + costed.reduce((s, l) => s + l.swap_min * l.qty, 0);
  const corrective = tasks.filter((t) => t.kind === 'corrective');
  const preventive = tasks.filter((t) => t.kind === 'preventive');

  const setQty = (sku: string, qty: number) => setLines((ls) => ls.map((l) => (l.sku === sku ? { ...l, qty: Math.max(1, Math.min(100, qty)) } : l)));
  const remove = (sku: string) => setLines((ls) => ls.filter((l) => l.sku !== sku));
  const add = (p: { sku: string; name: string; uom: string; unit_cost: number; swap_min?: number; service_affecting?: boolean }, onHand: number | null = null) => {
    setLines((ls) =>
      ls.some((l) => l.sku === p.sku)
        ? ls.map((l) => (l.sku === p.sku ? { ...l, qty: l.qty + 1 } : l))
        : [...ls, { sku: p.sku, name: p.name, uom: p.uom, qty: 1, unit_cost: p.unit_cost, on_hand: onHand, swap_min: p.swap_min ?? 0, service_affecting: !!p.service_affecting }],
    );
    setQ('');
  };

  const submit = async (asOverride: boolean) => {
    const payload = {
      site_id,
      lines: costed.map((l) => ({ sku: l.sku, qty: l.qty })),
      ticket: ticket.trim(),
      work_type: workType,
      notes: notes.trim(),
      tasks_done: tasks.filter((t) => done[t.id]).map((t) => t.title),
    };
    const title = `${asOverride ? 'Budget override' : 'Work order'} · ${a.site_name} · ${money2(total)}`;
    const req = asOverride
      ? await request('request_budget_override', { ...payload, reason: overrideReason.trim() || 'Parts exceed the remaining site budget' }, title)
      : await request('submit_work_order', payload, title);
    setReqId(req._id);
  };

  const notOnOrder = (plan?.lines ?? []).filter((l) => !lines.some((x) => x.sku === l.sku));
  const upgrades = (plan?.upgrades ?? []).filter((l) => !lines.some((x) => x.sku === l.sku));
  const depotName = cat?.depots[a.access.depot]?.name ?? a.access.depot;

  const TaskRow = ({ t }: { t: PlanTask }) => (
    <Pressable onPress={() => setDone((d) => ({ ...d, [t.id]: !d[t.id] }))} style={styles.task}>
      <Ionicons name={done[t.id] ? 'checkbox' : 'square-outline'} size={22} color={done[t.id] ? theme.color.ok : theme.color.faint} />
      <View style={{ flex: 1 }}>
        <Text style={[styles.lineName, done[t.id] && { color: theme.color.muted, textDecorationLine: 'line-through' }]}>{t.title}</Text>
        {t.alarm ? <Text style={styles.meta}>Alarm: {t.alarm}</Text> : null}
      </View>
      {t.severity ? <Pill label={t.severity} tone={SEVERITY_TONE[t.severity] ?? 'warn'} /> : <Text style={styles.meta}>{t.est_min} min</Text>}
    </Pressable>
  );

  return (
    <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
      <Card style={{ padding: 14, gap: 4 }}>
        <Text style={styles.meta}>WORK ORDER FOR</Text>
        <Text style={styles.h2}>{a.site_name}</Text>
        <Text style={styles.meta}>{a.site_code} · {a.site_type_name} · {a.sla.tier_name} SLA, restore in {a.sla.restore_hours}h · spares from {depotName}</Text>
      </Card>

      {reqId ? (
        <WorkOrderTracker id={reqId} onRetry={() => setReqId(null)} />
      ) : (
        <>
          <SectionTitle title="Work type" />
          <ChoiceRow options={(cat?.work_types ?? ['Preventive maintenance', 'Corrective maintenance']).map((w) => ({ value: w, label: w }))} value={workType} onChange={setWorkType} />

          {corrective.length ? (
            <>
              <SectionTitle title={`Corrective · ${corrective.length} open alarm${corrective.length > 1 ? 's' : ''}`} action={<Text style={styles.prov}>do these first</Text>} />
              <Card style={{ padding: 4 }}>{corrective.map((t) => <TaskRow key={t.id} t={t} />)}</Card>
            </>
          ) : null}

          <SectionTitle title={`Preventive checklist · ${preventive.filter((t) => done[t.id]).length}/${preventive.length}`} />
          <Card style={{ padding: 4 }}>
            {preventive.length ? preventive.map((t) => <TaskRow key={t.id} t={t} />) : <Text style={[styles.meta, { padding: 12 }]}>No checklist for this site type.</Text>}
          </Card>

          <SectionTitle title={`Parts · ${lines.length}`} action={plan ? <Text style={styles.prov}>pre-filled from the asset-health model</Text> : null} />
          <Card style={{ padding: 4 }}>
            {costed.length === 0 ? <Text style={[styles.meta, { padding: 12 }]}>No parts yet - add from the catalog below, or close out with checks only.</Text> : null}
            {costed.map((l, i) => (
              <View key={l.sku} style={[styles.line, i > 0 && styles.lineBorder]}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.lineName} numberOfLines={2}>{l.name}</Text>
                  <Text style={styles.meta}>
                    {money2(l.unit_cost)}/{l.uom}
                    {l.on_hand != null ? ` · ${l.on_hand} at depot` : ''}
                    {l.days_to_failure != null && l.days_to_failure <= 7 ? ` · fails in ~${Math.max(0, l.days_to_failure)}d` : ''}
                  </Text>
                  {l.service_affecting ? <Text style={[styles.meta, { color: theme.color.danger, fontWeight: '700' }]}>Service-affecting · needs an outage window</Text> : null}
                  {l.on_hand != null && l.on_hand < l.qty ? <Text style={[styles.meta, { color: theme.color.warn, fontWeight: '700' }]}>Only {l.on_hand} on hand - {l.qty - l.on_hand} will go on order</Text> : null}
                </View>
                <View style={styles.stepper}>
                  <Pressable onPress={() => (l.qty <= 1 ? remove(l.sku) : setQty(l.sku, l.qty - 1))} style={styles.step}><Ionicons name={l.qty <= 1 ? 'trash-outline' : 'remove'} size={16} color={theme.color.ink} /></Pressable>
                  <Text style={styles.qty}>{l.qty}</Text>
                  <Pressable onPress={() => setQty(l.sku, l.qty + 1)} style={styles.step}><Ionicons name="add" size={16} color={theme.color.ink} /></Pressable>
                </View>
                <Text style={styles.lineTotal}>{money2(l.total)}</Text>
              </View>
            ))}
          </Card>

          {affecting.length ? (
            <Card style={[styles.sugg, { marginTop: 10, backgroundColor: theme.color.dangerSoft }]}>
              <Ionicons name="power" size={20} color={theme.color.danger} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.lineName, { color: theme.color.danger }]}>{affecting.length} service-affecting part{affecting.length > 1 ? 's' : ''} · about {outageMin} min off-air</Text>
                <Text style={styles.meta}>The NOC has to grant an outage window before you start.</Text>
              </View>
              <Button small kind="light" label="Request" onPress={() =>
                openAction({ label: 'Outage window', tool: 'request_outage_window', args: { site_id, duration_min: outageMin, reason: `Service-affecting swap: ${affecting.map((l) => l.name.split(',')[0]).join(', ')}` } },
                  `Outage window · ${a.site_name} · ${outageMin} min`)} />
            </Card>
          ) : null}

          {notOnOrder.length || upgrades.length ? (
            <>
              <SectionTitle title="Also recommended" />
              <View style={{ gap: 8 }}>
                {notOnOrder.map((l) => (
                  <Pressable key={l.sku} onPress={() => add(l, l.on_hand_at_depot)}>
                    <Card style={styles.sugg}>
                      <Ionicons name="add-circle" size={20} color={theme.color.red} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.lineName} numberOfLines={1}>{l.qty} × {l.name}</Text>
                        <Text style={styles.meta}>{l.reason} · {money2(l.unit_cost)}/{l.uom}</Text>
                      </View>
                      <Pill label={`${Math.round((l.confidence ?? 0) * 100)}%`} tone="neutral" />
                    </Card>
                  </Pressable>
                ))}
                {upgrades.map((l) => (
                  <Pressable key={l.sku} onPress={() => add(l, l.on_hand_at_depot)}>
                    <Card style={styles.sugg}>
                      <Ionicons name="trending-up" size={20} color={theme.color.info} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.lineName} numberOfLines={1}>{l.name}</Text>
                        <Text style={styles.meta}>{l.reason} · {money2(l.unit_cost)}</Text>
                      </View>
                      <Pill label="Upgrade" tone="info" />
                    </Card>
                  </Pressable>
                ))}
              </View>
            </>
          ) : null}

          <SectionTitle title="Add from the parts catalog" />
          <View style={styles.search}>
            <Ionicons name="search" size={16} color={theme.color.faint} />
            <TextInput value={q} onChangeText={setQ} placeholder="Rectifier, SFP, battery, jumper…" placeholderTextColor={theme.color.faint} style={styles.input} />
          </View>
          {results.map((p) => (
            <Pressable key={p.sku} onPress={() => add(p)}>
              <Card style={styles.sugg}>
                <Ionicons name="add-circle-outline" size={20} color={theme.color.red} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName} numberOfLines={1}>{p.name}</Text>
                  <Text style={styles.meta}>{p.sku} · {p.spec} · {money2(p.unit_cost)}/{p.uom}{p.service_affecting ? ' · service-affecting' : ''}{a.wear[p.sku] ? ` · last replaced here ${a.wear[p.sku].last_replaced}` : ''}</Text>
                </View>
              </Card>
            </Pressable>
          ))}

          <SectionTitle title="Reference" />
          <Card style={{ padding: 14, gap: 10 }}>
            <TextInput value={ticket} onChangeText={setTicket} placeholder="Trouble ticket or change number (optional)" placeholderTextColor={theme.color.faint} style={styles.field} />
            <TextInput value={notes} onChangeText={setNotes} placeholder="Readings and notes (optional)" placeholderTextColor={theme.color.faint} style={styles.field} multiline />
          </Card>

          <SectionTitle title="Close out" />
          <Card style={{ padding: 14, gap: 6 }}>
            <Tot label={`Checklist tasks done`} text={`${doneCount} of ${tasks.length}`} />
            <Tot label="Estimated time on site" text={`${Math.floor(estMin / 60)}h ${estMin % 60}m`} />
            <View style={[styles.tot, { borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 8, marginTop: 2 }]}>
              <Text style={{ fontWeight: '900', color: theme.color.ink, fontSize: theme.type.lg }}>Parts total</Text>
              <Text style={{ fontWeight: '900', color: theme.color.red, fontSize: theme.type.xl }}>{money2(total)}</Text>
            </View>
            <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
              <Pill label={`Site budget left ${money2(available)}`} tone={c.on_hold ? 'danger' : overBudget ? 'warn' : 'ok'} icon="wallet-outline" />
              {short.length ? <Pill label={`${short.length} part${short.length > 1 ? 's' : ''} short at depot`} tone="warn" icon="cube-outline" /> : null}
              {offline ? <Pill label="Will send when connected" tone="warn" icon="cloud-upload-outline" /> : null}
            </View>
            {c.on_hold ? (
              <Text style={styles.warn}>This site is on an access hold ({c.hold_days} days: {c.hold_reason}). Work orders will be refused until the Site Access desk releases it.</Text>
            ) : overBudget ? (
              <>
                <Text style={styles.warn}>{money2(shortfall)} over the site's remaining maintenance budget. Submit as a budget override and Field Ops will approve it in the Agent Operations Manager.</Text>
                <TextInput value={overrideReason} onChangeText={setOverrideReason} placeholder="Reason for the override" placeholderTextColor={theme.color.faint} style={styles.field} />
                <Button label={`Submit as budget override · ${money2(total)}`} icon="shield-checkmark" onPress={() => void submit(true)} disabled={!lines.length} />
                <Button label="Try as a normal work order anyway" kind="ghost" onPress={() => void submit(false)} disabled={!lines.length} />
              </>
            ) : (
              <Button label={`Close out work order · ${money2(total)}`} icon="checkmark-done" onPress={() => void submit(false)} disabled={!lines.length || c.on_hold} />
            )}
            <Text style={styles.tiny}>Costed on this phone from the parts catalog in Couchbase Lite. The work order is saved locally and sent through Sync Gateway when you have a connection; Couchbase AOM runs it as a governed tool call.</Text>
          </Card>
        </>
      )}
    </ScrollView>
  );
}

function Tot({ label, text }: { label: string; text: string }) {
  return (
    <View style={styles.tot}>
      <Text style={styles.meta}>{label}</Text>
      <Text style={{ fontWeight: '700', color: theme.color.text }}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  h2: { fontSize: theme.type.xl, fontWeight: '900', color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center', lineHeight: 16 },
  warn: { color: theme.color.warn, fontWeight: '700', fontSize: theme.type.sm, lineHeight: 19 },
  prov: { color: theme.color.red, fontSize: theme.type.xs, fontWeight: '700' },
  task: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12 },
  line: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12 },
  lineBorder: { borderTopWidth: 1, borderTopColor: theme.color.border },
  lineName: { fontWeight: '700', color: theme.color.text, fontSize: theme.type.sm },
  lineTotal: { fontWeight: '800', color: theme.color.text, width: 78, textAlign: 'right' },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  step: { width: 30, height: 30, borderRadius: 15, backgroundColor: theme.color.bg, alignItems: 'center', justifyContent: 'center' },
  qty: { width: 26, textAlign: 'center', fontWeight: '900', color: theme.color.ink },
  sugg: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12, marginBottom: 2 },
  search: { flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: theme.color.surface, borderRadius: 999, paddingHorizontal: 14, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  input: { flex: 1, paddingVertical: 10, fontSize: theme.type.md, color: theme.color.text },
  field: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 11, fontSize: theme.type.md, color: theme.color.text },
  tot: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
});
