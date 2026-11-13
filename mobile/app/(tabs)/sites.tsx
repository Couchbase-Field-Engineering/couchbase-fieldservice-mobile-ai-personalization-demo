import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { Site } from '@/src/types';
import { Card, Empty, money, Pill } from '@/src/ui/components';

/** Every site in the area - all of it on the phone, searchable offline. */
export default function Sites() {
  const { snap, setCurrentSiteId } = useData();
  const insets = useSafeAreaInsets();
  const [q, setQ] = useState('');
  const today = snap.tech?.route_date ?? '';
  const list = useMemo(() => {
    const all = Object.values(snap.sites);
    const m = q.trim().toLowerCase();
    const f = m ? all.filter((a) => `${a.site_name} ${a.site_code} ${a.address.city} ${a.site_type_name} ${a.cluster?.cluster_name ?? ''}`.toLowerCase().includes(m)) : all;
    return f.sort((a, b) => (a.visit.next_visit_date < b.visit.next_visit_date ? -1 : a.visit.next_visit_date > b.visit.next_visit_date ? 1 : a.site_name.localeCompare(b.site_name)));
  }, [snap.sites, q]);

  const open = (a: Site) => {
    setCurrentSiteId(a.site_id);
    router.push({ pathname: '/site', params: { site_id: a.site_id } });
  };

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.bg }}>
      <View style={[styles.head, { paddingTop: insets.top + 12 }]}>
        <Text style={styles.h1}>Sites</Text>
        <Text style={styles.sub}>{snap.tech?.area_name ?? ''} · {Object.keys(snap.sites).length} on this phone</Text>
        <View style={styles.search}>
          <Ionicons name="search" size={16} color={theme.color.faint} />
          <TextInput value={q} onChangeText={setQ} placeholder="Site, code, city or site type" placeholderTextColor={theme.color.faint} style={styles.input} />
        </View>
      </View>
      <FlatList
        data={list}
        keyExtractor={(a) => a.site_id}
        contentContainerStyle={styles.body}
        ListEmptyComponent={<Empty icon="radio-outline" title="No sites yet" body="Your area syncs from Couchbase in a moment." />}
        renderItem={({ item: a }) => {
          const due = a.visit.next_visit_date <= today;
          const plan = snap.plans[a.site_id];
          return (
            <Pressable onPress={() => open(a)} style={({ pressed }) => [{ marginBottom: 10, opacity: pressed ? 0.92 : 1 }]}>
              <Card style={styles.card}>
                <View style={{ flex: 1, gap: 3 }}>
                  <Text style={styles.name}>{a.site_name}</Text>
                  <Text style={styles.meta}>{a.site_code} · {a.site_type_name} · {a.address.city}, {a.address.state}{a.cluster ? ` · ${a.cluster.cluster_name}` : ''}</Text>
                  <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
                    <Pill label={a.sla.tier_name} tone="neutral" icon="timer-outline" />
                    {a.alarms?.length ? <Pill label={`${a.alarms.length} alarm${a.alarms.length > 1 ? 's' : ''}`} tone="danger" icon="warning-outline" /> : null}
                    <Pill label={due ? 'Due today' : `Next ${a.visit.next_visit_date.slice(5)}`} tone={due ? 'red' : 'neutral'} icon="calendar-outline" />
                    {plan?.plan_total_usd ? <Pill label={`Parts ${money(plan.plan_total_usd)}`} tone="info" icon="construct-outline" /> : null}
                    {a.auth.on_hold ? <Pill label="Access hold" tone="danger" icon="lock-closed" /> : null}
                  </View>
                </View>
                <Ionicons name="chevron-forward" size={18} color={theme.color.faint} />
              </Card>
            </Pressable>
          );
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  head: { paddingHorizontal: 16, paddingBottom: 10, backgroundColor: theme.color.bg },
  h1: { fontSize: theme.type.title, fontWeight: '900', color: theme.color.ink },
  sub: { color: theme.color.muted, marginTop: 2 },
  search: { flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: theme.color.surface, borderRadius: 999, paddingHorizontal: 14, marginTop: 12, borderWidth: 1, borderColor: theme.color.border },
  input: { flex: 1, paddingVertical: 10, fontSize: theme.type.md, color: theme.color.text },
  body: { padding: 16, paddingTop: 6, maxWidth: 640, width: '100%', alignSelf: 'center' },
  card: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14 },
  name: { fontWeight: '800', color: theme.color.ink, fontSize: theme.type.md },
  meta: { color: theme.color.muted, fontSize: theme.type.sm },
});
