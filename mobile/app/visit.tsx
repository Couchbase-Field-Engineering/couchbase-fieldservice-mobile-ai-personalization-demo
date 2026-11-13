import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { ChoiceRow } from '@/src/ui/Choice';
import { Button, Card, Empty, SectionTitle } from '@/src/ui/components';
import { WorkOrderTracker } from '@/src/ui/WorkOrderTracker';

const OUTCOMES = [
  { value: 'work_completed', label: 'Work completed' },
  { value: 'no_fault_found', label: 'No fault found' },
  { value: 'follow_up', label: 'Follow up' },
  { value: 'no_access', label: 'No access' },
] as const;
const CADENCE = [7, 14, 30, 60, 90].map((d) => ({ value: String(d), label: `${d} days` }));

/** Log the stop: marks it visited on the route and schedules the next one. Works offline like everything else. */
export default function Visit() {
  const { site_id = '' } = useLocalSearchParams<{ site_id: string }>();
  const { snap, request } = useData();
  const a = snap.sites[site_id];
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]['value']>('work_completed');
  const [notes, setNotes] = useState('');
  const [cadence, setCadence] = useState(String(a?.visit.cadence_days ?? 30));
  const [reqId, setReqId] = useState<string | null>(null);
  if (!a) return <Empty icon="location-outline" title="Site not on this phone" body="Open a stop from your route first." />;

  const submit = async () => {
    const req = await request('log_site_visit', { site_id, outcome, notes: notes.trim(), next_visit_days: Number(cadence) }, `Visit · ${a.site_name} · ${outcome.replace(/_/g, ' ')}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
      <Card style={{ padding: 14, gap: 4 }}>
        <Text style={styles.meta}>VISIT</Text>
        <Text style={styles.h2}>{a.site_name}</Text>
        <Text style={styles.meta}>Last visit {a.visit.last_visit} · every {a.visit.cadence_days} days · {a.sla.tier_name} SLA</Text>
      </Card>
      {reqId ? (
        <WorkOrderTracker id={reqId} onRetry={() => setReqId(null)} />
      ) : (
        <>
          <SectionTitle title="Outcome" />
          <ChoiceRow options={OUTCOMES.map((o) => ({ value: o.value, label: o.label }))} value={outcome} onChange={setOutcome} />
          <SectionTitle title="Next visit in" />
          <ChoiceRow options={CADENCE} value={cadence} onChange={setCadence} />
          <SectionTitle title="Notes" />
          <Card style={{ padding: 14, gap: 12 }}>
            <TextInput value={notes} onChangeText={setNotes} placeholder="e.g. Gate lock replaced; landlord wants a call before roof access" placeholderTextColor={theme.color.faint} style={styles.field} multiline />
            <Button label="Log visit" icon="checkmark" onPress={() => void submit()} />
            <Text style={styles.tiny}>Saved on this phone; marks the stop visited on your route and syncs when connected.</Text>
          </Card>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center', paddingBottom: 40 },
  h2: { fontSize: theme.type.xl, fontWeight: '900', color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, textAlign: 'center' },
  field: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 11, fontSize: theme.type.md, color: theme.color.text, minHeight: 80 },
});
