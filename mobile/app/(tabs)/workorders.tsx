import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, money2, Pill, SectionTitle, STATUS_UI, SyncBadge } from '@/src/ui/components';
import { TOOL_ICON, TOOL_LABEL, openAction } from '@/src/ui/nav';

/** Every work order and field action from this phone, with its live status from Couchbase Lite. */
export default function WorkOrders() {
  const { snap, sync } = useData();
  const insets = useSafeAreaInsets();
  const queued = snap.workOrders.filter((o) => o._local || o.status === 'pending' || o.status === 'processing');
  const waiting = snap.workOrders.filter((o) => o.status === 'awaiting_approval' && !o._local);
  const done = snap.workOrders.filter((o) => !queued.includes(o) && !waiting.includes(o));
  const value = snap.workOrders.filter((o) => o.status === 'completed' || o.status === 'parts_pending').reduce((s, o) => s + Math.max(0, o.cost_usd ?? 0), 0);

  const Item = ({ id }: { id: string }) => {
    const q = snap.workOrders.find((o) => o._id === id)!;
    const ui = STATUS_UI[q.status] ?? STATUS_UI.pending;
    const budgetLimit = q.status === 'failed' && q.reason_code === 'budget_limit';
    return (
      <Card style={styles.item}>
        <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
          <View style={styles.ico}><Ionicons name={TOOL_ICON[q.tool] ?? 'flash'} size={16} color={theme.color.onDark} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title} numberOfLines={2}>{q.title}</Text>
            <Text style={styles.meta}>{TOOL_LABEL[q.tool] ?? q.tool} · {q.site_name ?? q.site_id} · {new Date(q.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</Text>
          </View>
          <Pill label={q._local ? 'On device' : ui.label} tone={q._local ? 'warn' : ui.tone} icon={ui.icon} />
        </View>
        {q.summary ? <Text style={[styles.summary, q.status === 'failed' && { color: theme.color.danger }]}>{q.summary}</Text> : null}
        {q.item?.backordered?.length ? (
          <Text style={[styles.meta, { color: theme.color.info, fontWeight: '700' }]}>
            On order: {q.item.backordered.map((b) => `${b.qty} × ${b.name.split(',')[0]} (ETA ${b.eta})`).join('; ')}
          </Text>
        ) : null}
        <Text style={styles.tiny}>
          {q.governed ? 'Governed by Couchbase Labs Agent Operations Manager' : q._local ? 'Queued in Couchbase Lite' : q.status === 'pending' ? 'Synced - waiting for the backend' : 'Processed'}
          {q.trace_id ? ` · trace ${q.trace_id.slice(0, 8)}` : ''}
          {q.cost_usd ? ` · ${money2(q.cost_usd)}` : ''}
        </Text>
        {budgetLimit ? (
          <Button
            small
            label={`Submit as budget override${q.auth ? ` · ${money2(q.auth.shortfall_usd)} over` : ''}`}
            icon="shield-checkmark-outline"
            onPress={() => openAction({ label: 'Budget override', tool: 'request_budget_override', args: { ...q.args, reason: 'Parts exceed the remaining site budget; failure predicted inside the SLA window' } }, `Budget override · ${q.site_name ?? q.site_id}`)}
          />
        ) : null}
      </Card>
    );
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <View>
          <Text style={styles.h1}>Work orders</Text>
          <Text style={styles.sub}>{snap.workOrders.length} from this phone · {money2(value)} of parts booked</Text>
        </View>
        <SyncBadge sync={sync} />
      </View>
      {snap.workOrders.length === 0 ? (
        <Empty icon="construct-outline" title="Nothing yet" body="Open a stop on your route and start its work order. It's saved here even with no signal." />
      ) : null}
      {queued.length ? (
        <>
          <SectionTitle title={`On device / syncing · ${queued.length}`} />
          {queued.map((q) => <Item key={q._id} id={q._id} />)}
          {sync.status === 'paused' || sync.status === 'offline' ? (
            <Pressable onPress={() => router.push('/(tabs)/profile')}>
              <Text style={styles.hint}>No connection - these send automatically when the replicator reconnects. Profile → turn "No signal" off to watch it happen.</Text>
            </Pressable>
          ) : null}
        </>
      ) : null}
      {waiting.length ? (
        <>
          <SectionTitle title={`Awaiting Field Ops · ${waiting.length}`} />
          {waiting.map((q) => <Item key={q._id} id={q._id} />)}
        </>
      ) : null}
      {done.length ? (
        <>
          <SectionTitle title="Completed" />
          {done.map((q) => <Item key={q._id} id={q._id} />)}
        </>
      ) : null}
      <View style={{ height: 30 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: theme.type.title, fontWeight: '900', color: theme.color.ink },
  sub: { color: theme.color.muted, marginTop: 2 },
  item: { padding: 12, gap: 8, marginBottom: 10 },
  ico: { width: 30, height: 30, borderRadius: 15, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
  title: { fontWeight: '800', color: theme.color.text },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  summary: { color: theme.color.text, fontSize: theme.type.sm, lineHeight: 19 },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs },
  hint: { color: theme.color.warn, fontSize: theme.type.sm, fontWeight: '600', marginBottom: 8, lineHeight: 19 },
});
