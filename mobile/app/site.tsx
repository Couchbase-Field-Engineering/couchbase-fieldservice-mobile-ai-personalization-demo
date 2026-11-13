import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, fmtDate, GradientArt, HealthBar, money, money2, Pill, SectionTitle, SEVERITY_TONE, STATUS_UI, type IconName } from '@/src/ui/components';

/** The stop: everything the technician needs on site, from Couchbase Lite. */
export default function SiteScreen() {
  const { site_id = '' } = useLocalSearchParams<{ site_id: string }>();
  const { snap, setCurrentSiteId } = useData();
  const a = snap.sites[site_id];
  const plan = snap.plans[site_id];
  useEffect(() => {
    if (site_id) setCurrentSiteId(site_id);
  }, [site_id, setCurrentSiteId]);
  if (!a) return <Empty icon="radio-outline" title="Site not on this phone" body="It isn't in your area, or hasn't synced yet." />;

  const c = a.auth;
  const available = c.budget_limit_usd + (c.temporary_extension_usd ?? 0) - c.committed_usd;
  const depot = snap.catalog?.depots[a.access.depot];
  const selected = plan?.lines.filter((l) => l.selected) ?? [];
  const tasks = plan?.tasks ?? [];
  const corrective = tasks.filter((t) => t.kind === 'corrective').length;
  const workOrders = snap.workOrders.filter((o) => o.site_id === site_id).slice(0, 3);
  const noSignal = !/good signal/i.test(a.visit.signal_note ?? '');
  const alarms = a.alarms ?? [];
  const risk = Math.round((a.ml_scores.outage_risk ?? 0) * 100);

  return (
    <ScrollView contentContainerStyle={styles.body}>
      <Card>
        <GradientArt palette="site" icon="radio" height={128}>
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
            <Pill label={a.site_type_name} tone="dark" icon="radio-outline" />
            <Pill label={`${a.sla.tier_name} · restore ${a.sla.restore_hours}h`} tone="dark" icon="timer-outline" />
            {a.cluster ? <Pill label={`${a.cluster.cluster_name} · ${a.cluster.sites} sites`} tone="dark" /> : null}
          </View>
          <View>
            <Text style={styles.code}>{a.site_code}</Text>
            <Text style={styles.title} numberOfLines={2}>{a.site_name}</Text>
          </View>
        </GradientArt>
        <View style={{ padding: 14, gap: 8 }}>
          <Row icon="location-outline" label="Address" value={`${a.address.street}, ${a.address.city}, ${a.address.state} ${a.address.zip}`} />
          <Row icon="person-outline" label="Contacts" value={a.contacts.map((k) => `${k.name} (${k.role}) ${k.phone}`).join('\n')} />
          <Row icon="key-outline" label="Access" value={`${a.access.access_hours} · ${a.access.climb_required ? 'tower climb required' : 'no climb'}${a.access.notes ? ` · ${a.access.notes}` : ''}`} />
          <Row icon="cellular-outline" label="Signal" value={a.visit.signal_note} tone={noSignal ? 'warn' : undefined} />
        </View>
      </Card>

      <View style={styles.kpis}>
        <Kpi label="OPEN ALARMS" value={String(alarms.length)} tone={alarms.length ? 'danger' : 'ok'} />
        <Kpi label="OUTAGE RISK 30D" value={`${risk}%`} tone={risk >= 50 ? 'danger' : risk >= 25 ? 'warn' : 'ok'} />
        <Kpi label="AVAILABILITY 30D" value={`${a.kpis?.availability_30d_pct ?? '-'}%`} />
      </View>

      {alarms.length ? (
        <>
          <SectionTitle title="Open alarms" action={<Text style={styles.prov}>corrective</Text>} />
          <Card style={{ padding: 4 }}>
            {alarms.map((al, i) => (
              <View key={al.alarm_id} style={[styles.alarm, i > 0 && { borderTopWidth: 1, borderTopColor: theme.color.border }]}>
                <Ionicons name="warning" size={18} color={al.severity === 'minor' ? theme.color.warn : theme.color.danger} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName}>{al.text}</Text>
                  <Text style={styles.meta}>{al.code} · raised {fmtDate(al.raised_at)}{al.action ? ` · ${al.action}` : ''}</Text>
                </View>
                <Pill label={al.severity} tone={SEVERITY_TONE[al.severity] ?? 'warn'} />
              </View>
            ))}
          </Card>
        </>
      ) : null}

      {plan?.briefing?.length ? (
        <>
          <SectionTitle title="Before you open the cabinet" />
          <Card style={{ padding: 14, gap: 8 }}>
            {plan.briefing.map((t, i) => (
              <View key={i} style={{ flexDirection: 'row', gap: 8 }}>
                <Ionicons name="sparkles" size={14} color={theme.color.red} style={{ marginTop: 3 }} />
                <Text style={{ flex: 1, color: theme.color.text, lineHeight: 20 }}>{t}</Text>
              </View>
            ))}
          </Card>
        </>
      ) : null}

      <SectionTitle title="Work plan" action={plan ? <Text style={styles.prov}>{plan.model_version}</Text> : null} />
      <Card style={{ padding: 14, gap: 10 }}>
        {plan ? (
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
            <Pill label={plan.work_type} tone={corrective ? 'danger' : 'ok'} icon="construct-outline" />
            <Pill label={`${corrective} corrective · ${tasks.length - corrective} preventive tasks`} tone="neutral" icon="list-outline" />
            <Pill label={`~${Math.floor(plan.est_minutes / 60)}h ${plan.est_minutes % 60}m`} tone="neutral" icon="time-outline" />
          </View>
        ) : null}
        {plan && selected.length ? (
          <>
            {selected.slice(0, 4).map((l) => (
              <View key={l.sku} style={styles.line}>
                <Text style={styles.qty}>{l.qty}×</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName} numberOfLines={1}>{l.name}</Text>
                  <Text style={styles.meta}>{l.reason}</Text>
                </View>
                <Text style={styles.lineTotal}>{money2(l.line_total)}</Text>
              </View>
            ))}
            {selected.length > 4 ? <Text style={styles.meta}>+ {selected.length - 4} more parts</Text> : null}
            <View style={[styles.line, { borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 10 }]}>
              <Text style={{ flex: 1, fontWeight: '800', color: theme.color.ink }}>{selected.length} recommended parts</Text>
              <Text style={styles.total}>{money2(plan.plan_total_usd)}</Text>
            </View>
            {!plan.auth.ok ? (
              <View style={[styles.flag, plan.auth.on_hold ? { backgroundColor: theme.color.dangerSoft } : { backgroundColor: theme.color.warnSoft }]}>
                <Ionicons name="alert-circle" size={16} color={plan.auth.on_hold ? theme.color.danger : theme.color.warn} />
                <Text style={{ flex: 1, color: plan.auth.on_hold ? theme.color.danger : theme.color.warn, fontWeight: '700', fontSize: theme.type.sm }}>
                  {plan.auth.on_hold
                    ? `Access hold for ${c.hold_days} days - ${c.hold_reason}. No work can be booked until it is released.`
                    : `${money2(plan.auth.shortfall_usd)} over the remaining site budget - submit as a budget override for Field Ops.`}
                </Text>
              </View>
            ) : null}
          </>
        ) : (
          <Text style={styles.meta}>No parts predicted to fail according to this morning's asset-health scores. Run the checklist and log the visit.</Text>
        )}
        <Button label="Start work order" icon="construct" onPress={() => router.push({ pathname: '/workorder', params: { site_id } })} />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <View style={{ flex: 1 }}><Button small kind="ghost" label="Ask assistant" icon="sparkles-outline" onPress={() => router.push('/(tabs)/assistant')} /></View>
          <View style={{ flex: 1 }}><Button small kind="ghost" label="Log visit" icon="location-outline" onPress={() => router.push({ pathname: '/visit', params: { site_id } })} /></View>
        </View>
      </Card>

      {a.assets?.length ? (
        <>
          <SectionTitle title="Asset health" action={<Text style={styles.prov}>{a.ml_scores.segment}</Text>} />
          <Card style={{ padding: 14, gap: 10 }}>
            {a.assets.map((x) => (
              <View key={x.asset_id} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <Text style={[styles.lineName, { width: 150 }]} numberOfLines={1}>{x.name}</Text>
                <HealthBar value={x.health} />
                <Text style={[styles.meta, { width: 30, textAlign: 'right', fontWeight: '800', color: x.status === 'ok' ? theme.color.text : x.status === 'alarm' ? theme.color.danger : theme.color.warn }]}>{x.health}</Text>
              </View>
            ))}
            <Text style={styles.meta}>Serves about {(a.kpis?.subscribers_served ?? 0).toLocaleString('en-US')} subscribers · {a.kpis?.outage_min_30d ?? 0} outage minutes in 30 days</Text>
          </Card>
        </>
      ) : null}

      <SectionTitle title="SLA & budget" />
      <Card style={{ padding: 14, gap: 8 }}>
        <Row icon="timer-outline" label="SLA" value={`${a.sla.tier_name} · restore within ${a.sla.restore_hours}h · support agreement ${a.sla.agreement_id} renews ${fmtDate(a.sla.renewal_date)}`} />
        <Row icon="wallet-outline" label="Budget" value={`${money2(available)} left of ${money(c.budget_limit_usd)} this quarter · ${money2(c.committed_usd)} committed`} tone={c.on_hold ? 'danger' : available < c.budget_limit_usd * 0.25 ? 'warn' : undefined} />
        <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.min(100, Math.round((c.committed_usd / c.budget_limit_usd) * 100))}%`, backgroundColor: c.on_hold ? theme.color.danger : theme.color.red }]} /></View>
        {c.on_hold ? <Row icon="lock-closed-outline" label="Hold" value={`${c.hold_days} days · ${c.hold_reason}`} tone="danger" /> : null}
        <Row icon="cube-outline" label="Spares" value={`${depot?.name ?? a.access.depot}${depot ? ` (${depot.city})` : ''}`} />
        {a.recurring_tasks.length ? <Row icon="repeat-outline" label="Recurring" value={a.recurring_tasks.map((s) => `${s.qty} × ${s.name.split(',')[0]} every ${s.cadence_weeks}w`).join('\n')} /> : null}
        {a.outage_windows?.length ? <Row icon="power-outline" label="Windows" value={a.outage_windows.slice(0, 2).map((w) => `${w.window_id} · ${w.duration_min} min · ${w.date}`).join('\n')} /> : null}
      </Card>

      <SectionTitle title="Work history" action={<Text style={styles.prov}>{money(a.maintenance.last_12mo_usd)} / 12 mo</Text>} />
      {a.work_history.slice(0, 6).map((o) => (
        <Card key={o.work_order_id} style={styles.hist}>
          <Ionicons name={o.source === 'field_tech' ? 'person' : o.source === 'scheduled_pm' ? 'calendar-outline' : o.source === 'noc_dispatch' ? 'pulse-outline' : 'business-outline'} size={16} color={theme.color.red} />
          <View style={{ flex: 1 }}>
            <Text style={styles.histTitle}>{o.work_order_id} · {fmtDate(o.date)}</Text>
            <Text style={styles.meta}>{o.work_type ?? 'Maintenance'} · {o.line_count} parts · {(o.source ?? '').replace(/_/g, ' ')}{o.backordered?.length ? ' · parts on order' : ''}{o.budget_override ? ' · budget override' : ''}</Text>
          </View>
          <Text style={styles.histTotal}>{money2(o.total_usd)}</Text>
        </Card>
      ))}

      {workOrders.length ? (
        <>
          <SectionTitle title="From this phone" />
          {workOrders.map((q) => {
            const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
            return (
              <Card key={q._id} style={styles.hist}>
                <Ionicons name={ui.icon} size={16} color={theme.color.red} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.histTitle}>{q.title}</Text>
                  {q.summary ? <Text style={styles.meta} numberOfLines={2}>{q.summary}</Text> : null}
                </View>
                <Pill label={q._local ? 'On device' : ui.label} tone={q._local ? 'warn' : ui.tone} />
              </Card>
            );
          })}
        </>
      ) : null}
      <Text style={styles.tiny}>Site revision {a.rev} · export {a.export_date}. Every work order bumps the revision, which invalidates the assistant's context cache for this site.</Text>
    </ScrollView>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warn' | 'danger' }) {
  const color = tone === 'danger' ? theme.color.danger : tone === 'warn' ? theme.color.warn : tone === 'ok' ? theme.color.ok : theme.color.ink;
  return (
    <Card style={styles.kpi}>
      <Text style={[styles.kpiNum, { color }]}>{value}</Text>
      <Text style={styles.kpiLbl}>{label}</Text>
    </Card>
  );
}

function Row({ icon, label, value, tone }: { icon: IconName; label: string; value: string; tone?: 'warn' | 'danger' }) {
  const color = tone === 'danger' ? theme.color.danger : tone === 'warn' ? theme.color.warn : theme.color.text;
  return (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={16} color={theme.color.red} style={{ marginTop: 1 }} />
      <Text style={[styles.meta, { width: 76 }]}>{label}</Text>
      <Text style={{ flex: 1, color, fontWeight: '600', fontSize: theme.type.sm, lineHeight: 19 }} selectable>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  title: { color: theme.color.onDark, fontSize: theme.type.xl, fontWeight: '900' },
  code: { color: theme.color.onDarkMuted, fontSize: theme.type.xs, fontWeight: '800', letterSpacing: 1.4 },
  kpis: { flexDirection: 'row', gap: 8, marginTop: 12 },
  kpi: { flex: 1, padding: 12, alignItems: 'center', gap: 2 },
  kpiNum: { fontSize: theme.type.xl, fontWeight: '900' },
  kpiLbl: { color: theme.color.muted, fontSize: 9, fontWeight: '800', letterSpacing: 1 },
  alarm: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12 },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center', marginTop: 18, lineHeight: 16 },
  prov: { color: theme.color.red, fontSize: theme.type.xs, fontWeight: '700' },
  line: { flexDirection: 'row', gap: 10, alignItems: 'center' },
  qty: { width: 34, fontWeight: '900', color: theme.color.ink },
  lineName: { fontWeight: '700', color: theme.color.text, fontSize: theme.type.sm },
  lineTotal: { fontWeight: '800', color: theme.color.text },
  total: { fontWeight: '900', color: theme.color.red, fontSize: theme.type.lg },
  flag: { flexDirection: 'row', gap: 8, alignItems: 'center', borderRadius: theme.radiusSm, padding: 10 },
  bar: { height: 6, borderRadius: 3, backgroundColor: theme.color.bg, overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3 },
  hist: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12, marginBottom: 8 },
  histTitle: { fontWeight: '700', color: theme.color.text },
  histTotal: { fontWeight: '800', color: theme.color.text },
});
