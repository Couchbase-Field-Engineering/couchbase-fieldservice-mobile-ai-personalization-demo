import { Ionicons } from '@expo/vector-icons';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { API_URL } from '@/src/config';
import { useData } from '@/src/data/DataContext';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { Button, Card, money, Pill, SectionTitle, SyncBadge, type IconName } from '@/src/ui/components';

export default function Profile() {
  const { snap, sync, offline, setOffline, dbLocation } = useData();
  const { signOut, session } = useAuth();
  const insets = useSafeAreaInsets();
  const r = snap.tech;
  const sites = Object.values(snap.sites);
  const work_plans = Object.keys(snap.plans).length;
  const contexts = Object.keys(snap.contexts).length;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: theme.color.bg }} contentContainerStyle={[styles.body, { paddingTop: insets.top + 12 }]}>
      <Text style={styles.h1}>Profile</Text>
      {r ? (
        <Card style={{ padding: 16, marginTop: 12, gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={styles.avatar}><Text style={{ fontWeight: '900', color: theme.color.onDark, fontSize: 18 }}>{r.first_name[0]}{r.last_name[0]}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{r.first_name} {r.last_name}</Text>
              <Text style={styles.meta}>{r.email} · #{r.employee_id}</Text>
            </View>
          </View>
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            <Pill label={r.area_name} tone="red" icon="map-outline" />
            <Pill label={`${r.site_count} sites`} tone="neutral" />
            <Pill label={`${r.open_alarms ?? 0} open alarms`} tone="neutral" icon="warning-outline" />
            {(r.certifications ?? []).map((cert) => <Pill key={cert} label={cert} tone="neutral" icon="ribbon-outline" />)}
          </View>
        </Card>
      ) : null}

      <SectionTitle title="Offline & sync" />
      <Card style={{ padding: 16, gap: 10 }}>
        <SyncBadge sync={sync} />
        <Row icon="server-outline" label="Local database" value={sync.engine === 'couchbase-lite' ? 'Couchbase Lite' : 'Browser preview (in-memory)'} />
        <Row icon="folder-outline" label="Location" value={dbLocation ?? '—'} />
        <Row icon="swap-vertical-outline" label="Replicating with" value={sync.endpoint ?? '—'} />
        <Row icon="time-outline" label="Last sync" value={sync.lastSyncAt ? new Date(sync.lastSyncAt).toLocaleTimeString() : '—'} />
        <Row icon="cloud-upload-outline" label="Waiting to send" value={String(sync.pendingPush)} />
        <Row icon="layers-outline" label="On this phone" value={`${sites.length} sites · ${work_plans} work plans · ${snap.workOrders.length} work orders · ${contexts} cached contexts · catalog ${snap.catalog?.products.length ?? 0} parts`} />
        {sync.detail ? <Text style={[styles.tiny, { color: theme.color.danger }]}>{sync.detail}</Text> : null}
        <View style={styles.switchRow}>
          <View style={{ flex: 1 }}>
            <Text style={{ fontWeight: '800', color: theme.color.text }}>No signal</Text>
            <Text style={styles.meta}>Pause replication to demo the steel shelter: open sites, work through the plan, close out work orders, ask the assistant - all from Couchbase Lite. Work orders queue and send when you switch back.</Text>
          </View>
          <Switch value={offline} onValueChange={setOffline} trackColor={{ true: theme.color.red, false: theme.color.border }} thumbColor={theme.color.surface} />
        </View>
      </Card>

      <SectionTitle title="Where the data comes from" />
      <Card style={{ padding: 16, gap: 8 }}>
        <Row icon="analytics-outline" label="Source" value={`Databricks daily export · ${r?.export_date ?? '—'} · one job a night`} />
        <Row icon="git-branch-outline" label="Model" value={Object.values(snap.plans)[0]?.model_version ?? 'telco-asset-health'} />
        <Row icon="cube-outline" label="Served by" value="Couchbase Server → Sync Gateway → Couchbase Lite. No SQL warehouse or Model Serving call per screen." />
        <Text style={styles.tiny}>Area channel: every site and work plan in {r?.area_name ?? 'your area'} syncs to this phone; your own channel carries the route, work orders and assistant history.</Text>
      </Card>

      <SectionTitle title="Couchbase Labs Agent Operations Manager" />
      <Card style={{ padding: 16, gap: 8 }}>
        <Text style={styles.meta}>
          Every work order, budget override, outage window, recurring task, RMA and visit log becomes a request that the Field Service Assistant agent runs
          through Couchbase Labs Agent Operations Manager: RBAC and tool scope, human approval for budget overrides and outage windows, a trace and an audit entry.
          Assistant answers use Couchbase Labs Agent Operations Manager's Knowledge Base, Context Cache, memory and LLM cache.
        </Text>
        <Row icon="link-outline" label="Backend" value={API_URL} />
        <Row icon="finger-print-outline" label="Tech ID" value={session?.tech_id ?? '—'} />
      </Card>

      <View style={{ marginVertical: 24 }}>
        <Button label="Sign out" kind="ghost" icon="log-out-outline" onPress={() => void signOut()} />
      </View>
    </ScrollView>
  );
}

function Row({ icon, label, value }: { icon: IconName; label: string; value: string }) {
  return (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Ionicons name={icon} size={16} color={theme.color.red} style={{ marginTop: 1 }} />
      <Text style={[styles.meta, { width: 110 }]}>{label}</Text>
      <Text style={{ flex: 1, color: theme.color.text, fontWeight: '600', fontSize: theme.type.sm, lineHeight: 19 }} selectable>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  body: { padding: 16, maxWidth: 640, width: '100%', alignSelf: 'center' },
  h1: { fontSize: theme.type.title, fontWeight: '900', color: theme.color.ink },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: theme.type.xl, fontWeight: '900', color: theme.color.ink },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
  tiny: { color: theme.color.faint, fontSize: theme.type.xs, lineHeight: 16 },
  switchRow: { flexDirection: 'row', gap: 12, alignItems: 'center', borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 12, marginTop: 4 },
});
