import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, money2, Pill } from '@/src/ui/components';
import { TOOL_LABEL } from '@/src/ui/nav';
import { WorkOrderTracker } from '@/src/ui/WorkOrderTracker';

const NEEDS_APPROVAL = new Set(['request_budget_override', 'request_outage_window']);
const BLURB: Record<string, string> = {
  request_budget_override: 'Field Ops reviews budget overrides in the Agent Operations Manager before the work order is closed. You\'ll see their decision here.',
  request_outage_window: 'The NOC reviews outage windows in the Agent Operations Manager. Do not start service-affecting work until the grant shows here.',
  set_recurring_task: 'The part is added to the preventive visit nearest each due date, and drops off the model\'s recommendations.',
  create_rma: 'Creates an RMA, credits the cost back to the site budget and sets a depot return date five business days out.',
  log_site_visit: 'Marks the stop visited on your route and schedules the next visit.',
  submit_work_order: 'Costed against the site\'s maintenance budget; depot stock is issued when it syncs.',
};

/** One-tap actions from the Assistant and the Work orders list land here before they're queued. */
export default function Confirm() {
  const { tool = '', args = '{}', title = '' } = useLocalSearchParams<{ tool: string; args: string; title: string }>();
  const { request, snap } = useData();
  const [reqId, setReqId] = useState<string | null>(null);
  const parsed = JSON.parse(args) as Record<string, unknown> & { site_id?: string; reason?: string; lines?: { sku: string; qty: number }[] };
  const [reason, setReason] = useState(String(parsed.reason ?? ''));
  const a = parsed.site_id ? snap.sites[parsed.site_id] : null;
  if (!parsed.site_id || !a) return <Empty icon="alert-circle-outline" title="No site" body="This action needs a site from your area." />;

  const submit = async () => {
    const req = await request(tool, { ...parsed, site_id: parsed.site_id!, ...(reason ? { reason } : {}) }, title || `${TOOL_LABEL[tool] ?? tool} · ${a.site_name}`);
    setReqId(req._id);
  };
  const lines = parsed.lines ?? [];
  const products = snap.catalog?.products ?? [];

  return (
    <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
      {reqId ? <WorkOrderTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <Card style={{ padding: 18, gap: 12 }}>
          <Pill label={TOOL_LABEL[tool] ?? tool} tone={NEEDS_APPROVAL.has(tool) ? 'red' : 'info'} />
          <Text style={styles.h2}>{title}</Text>
          <Text style={styles.meta}>{a.site_name} · {a.site_code} · {a.sla.tier_name} SLA</Text>
          {lines.length ? (
            <Text style={styles.lines}>
              {lines.map((l) => `${l.qty} × ${(products.find((p) => p.sku === l.sku)?.name ?? l.sku).split(',')[0]}`).join('\n')}
            </Text>
          ) : null}
          {Object.entries(parsed).filter(([k]) => !['site_id', 'lines', 'reason'].includes(k)).map(([k, v]) => (
            <Text key={k} style={styles.meta}>{k.replace(/_/g, ' ')}: {typeof v === 'number' && k.endsWith('usd') ? money2(v) : Array.isArray(v) ? `${v.length} recorded` : String(v)}</Text>
          ))}
          {'reason' in parsed || NEEDS_APPROVAL.has(tool) ? (
            <TextInput value={reason} onChangeText={setReason} placeholder="Reason (goes on the audit trail)" placeholderTextColor={theme.color.faint} style={styles.field} />
          ) : null}
          <Text style={styles.meta}>{BLURB[tool] ?? 'Saved on this phone and sent as soon as you\'re connected.'}</Text>
          <Button label={NEEDS_APPROVAL.has(tool) ? 'Submit for approval' : 'Confirm'} icon="checkmark" onPress={() => void submit()} />
        </Card>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h2: { fontSize: theme.type.xl, fontWeight: '900', color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm, lineHeight: 19 },
  lines: { color: theme.color.text, fontSize: theme.type.sm, lineHeight: 20, backgroundColor: theme.color.bg, borderRadius: theme.radiusSm, padding: 10 },
  field: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 11, fontSize: theme.type.md, color: theme.color.text },
});
