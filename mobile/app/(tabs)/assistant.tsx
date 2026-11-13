import { Ionicons } from '@expo/vector-icons';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { ChatMessage } from '@/src/types';
import { Pill, SyncBadge } from '@/src/ui/components';
import { openAction } from '@/src/ui/nav';

const PROMPTS_SITE = [
  'What needs doing at this site today?',
  'What alarms are open here?',
  'Do I need an outage window for this work?',
  'Are battery blocks in stock at the depot?',
  'How much budget is left at this site?',
  'What was done here last time?',
];
const PROMPTS_GENERAL = ['How does a budget override work?', 'How do I test a battery string?', 'How do I clear a high VSWR alarm?', 'What are the rules for climbing a tower?'];

function llmLabel(m: ChatMessage): { label: string; tone: 'ok' | 'info' | 'neutral' | 'warn' } | null {
  if (m.offline) return { label: 'Answered on device · Couchbase Lite', tone: 'warn' };
  const s = m.llm?.status;
  if (!s) return null;
  if (s === 'hit_exact') return { label: 'LLM cache · exact hit', tone: 'ok' };
  if (s === 'hit_semantic') return { label: `LLM cache · semantic hit${m.llm?.similarity ? ` ${m.llm.similarity.toFixed(2)}` : ''}`, tone: 'ok' };
  if (s === 'miss') return { label: `LLM cache · miss${m.llm?.latency_ms ? ` · ${Math.round(m.llm.latency_ms)}ms` : ''}`, tone: 'neutral' };
  if (s === 'local') return { label: 'Composed from context (Couchbase Labs Agent Operations Manager not configured)', tone: 'neutral' };
  if (s === 'skipped') return null;
  if (s === 'bypass') return { label: 'LLM cache · bypassed', tone: 'neutral' };
  return { label: `LLM · ${s}`, tone: 'warn' };
}

export default function Assistant() {
  const { snap, sync, ask, thinking, liveChat, currentSiteId, setCurrentSiteId } = useData();
  const insets = useSafeAreaInsets();
  const [text, setText] = useState('');
  const scroll = useRef<ScrollView>(null);
  const firstLive = liveChat[0]?.at;
  const history = (snap.chat?.messages ?? []).filter((m) => !firstLive || m.at < firstLive).slice(-10);
  const messages = [...history, ...liveChat];
  const site = currentSiteId ? snap.sites[currentSiteId] : null;
  const stops = snap.tech?.route ?? [];

  useEffect(() => {
    setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [messages.length, thinking]);

  const send = (q: string) => {
    if (!q.trim()) return;
    setText('');
    void ask(q.trim());
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: theme.color.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={60}>
      <View style={[styles.header, { paddingTop: insets.top + 10 }]}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={styles.bot}><Ionicons name="sparkles" size={18} color={theme.color.onDark} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Assistant</Text>
            <Text style={styles.subtitle}>Field Service Assistant agent · governed by Couchbase Labs Agent Operations Manager</Text>
          </View>
        </View>
        <View style={{ marginTop: 10, flexDirection: 'row', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <SyncBadge sync={sync} dark />
          <Pill label={site ? `For: ${site.site_name}` : 'No site open'} tone="dark" icon="radio-outline" />
        </View>
      </View>

      {stops.length ? (
        <ScrollView horizontal style={{ flexGrow: 0, backgroundColor: theme.color.ink }} showsHorizontalScrollIndicator={false} contentContainerStyle={styles.stops}>
          {stops.map((s) => (
            <Pressable key={s.site_id} onPress={() => setCurrentSiteId(currentSiteId === s.site_id ? null : s.site_id)} style={[styles.stopChip, currentSiteId === s.site_id && styles.stopOn]}>
              <Text style={[styles.stopText, currentSiteId === s.site_id && { color: theme.color.onDark }]}>{s.site_name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      <ScrollView ref={scroll} style={{ flex: 1 }} contentContainerStyle={styles.list}>
        {messages.length === 0 ? (
          <View style={styles.intro}>
            <Text style={styles.introTitle}>{site ? `Ask me anything about ${site.site_name}.` : 'Pick a stop and ask away.'}</Text>
            <Text style={styles.introBody}>
              Work plan, open alarms, parts and depot stock, outage windows, budget, access and history. Answers come from the site's context cache
              in Couchbase and Couchbase Labs Agent Operations Manager's Knowledge Base - and when you're offline, straight from this phone. Nothing here queries Databricks.
            </Text>
          </View>
        ) : null}
        {messages.map((m) => <Bubble key={m.id} m={m} siteName={m.site_id ? snap.sites[m.site_id]?.site_name : undefined} />)}
        {thinking ? (
          <View style={[styles.bubble, styles.botBubble, { flexDirection: 'row', gap: 8, alignItems: 'center' }]}>
            <ActivityIndicator color={theme.color.red} />
            <Text style={{ color: theme.color.muted }}>Checking the context cache…</Text>
          </View>
        ) : null}
      </ScrollView>

      <ScrollView horizontal style={{ flexGrow: 0 }} showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} keyboardShouldPersistTaps="handled">
        {(site ? [...PROMPTS_SITE, ...PROMPTS_GENERAL] : PROMPTS_GENERAL).map((p) => (
          <Pressable key={p} onPress={() => send(p)} style={styles.chip}>
            <Text style={styles.chipText}>{p}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={[styles.inputRow, { paddingBottom: 10 }]}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder={site ? `Ask about ${site.site_name.split(' ')[0]}…` : 'Ask about procedures, parts, safety…'}
          placeholderTextColor={theme.color.faint}
          style={styles.input}
          onSubmitEditing={() => send(text)}
          returnKeyType="send"
        />
        <Pressable onPress={() => send(text)} style={styles.send} disabled={!text.trim()}>
          <Ionicons name="arrow-up" size={20} color={theme.color.onDark} />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function Bubble({ m, siteName }: { m: ChatMessage; siteName?: string }) {
  const [open, setOpen] = useState(false);
  if (m.role === 'tech') {
    return (
      <View style={[styles.bubble, styles.meBubble]}>
        <Text style={{ color: theme.color.onDark, fontSize: theme.type.md }}>{m.text}</Text>
        {siteName ? <Text style={{ color: theme.color.onDarkMuted, fontSize: theme.type.xs, marginTop: 4 }}>{siteName}</Text> : null}
      </View>
    );
  }
  const llm = llmLabel(m);
  const ctx = m.context;
  return (
    <View style={[styles.bubble, styles.botBubble]}>
      <Text style={{ color: theme.color.text, fontSize: theme.type.md, lineHeight: 21 }}>{m.text}</Text>
      {m.actions?.length ? (
        <View style={{ gap: 8, marginTop: 10 }}>
          {m.actions.map((a) => (
            <Pressable key={a.label} onPress={() => openAction(a, a.label)} style={styles.action}>
              <Ionicons name={a.tool ? 'flash' : 'open-outline'} size={14} color={theme.color.onDark} />
              <Text style={styles.actionText}>{a.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      <View style={styles.meta}>
        {ctx && !m.offline && ctx.status !== 'skipped' ? (
          <Pill
            label={`Context cache · ${ctx.status === 'hit' ? 'hit' : 'built'} ${Math.round(ctx.latency_ms)}ms`}
            tone={ctx.status === 'hit' ? 'ok' : 'info'}
            icon={ctx.status === 'hit' ? 'flash' : 'layers-outline'}
          />
        ) : null}
        {llm ? <Pill label={llm.label} tone={llm.tone} icon={m.offline ? 'airplane' : 'hardware-chip-outline'} /> : null}
        {m.sources?.length ? (
          <Pressable onPress={() => setOpen(!open)}>
            <Pill label={`${m.sources.length} sources ${open ? '▲' : '▼'}`} tone="neutral" icon="library-outline" />
          </Pressable>
        ) : null}
      </View>
      {open
        ? m.sources?.map((s, i) => (
            <View key={i} style={styles.source}>
              <Text style={styles.sourceTitle}>{s.title} <Text style={{ color: theme.color.faint }}>({s.kind})</Text></Text>
              <Text style={styles.sourceText} numberOfLines={3}>{s.snippet}</Text>
            </View>
          ))
        : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { backgroundColor: theme.color.ink, paddingHorizontal: 16, paddingBottom: 12 },
  bot: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
  title: { color: theme.color.onDark, fontSize: theme.type.xl, fontWeight: '900' },
  subtitle: { color: theme.color.onDarkMuted, fontSize: theme.type.xs },
  stops: { gap: 6, paddingHorizontal: 12, paddingBottom: 12 },
  stopChip: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: 'rgba(255,255,255,0.12)' },
  stopOn: { backgroundColor: theme.color.red },
  stopText: { color: theme.color.onDarkMuted, fontWeight: '700', fontSize: theme.type.xs },
  list: { padding: 14, gap: 10, maxWidth: 680, width: '100%', alignSelf: 'center' },
  intro: { backgroundColor: theme.color.surface, borderRadius: theme.radius, padding: 16, gap: 6 },
  introTitle: { fontWeight: '900', fontSize: theme.type.lg, color: theme.color.ink },
  introBody: { color: theme.color.muted, lineHeight: 20 },
  bubble: { padding: 13, borderRadius: 18, maxWidth: '88%' },
  meBubble: { backgroundColor: theme.color.red, alignSelf: 'flex-end', borderBottomRightRadius: 6 },
  botBubble: { backgroundColor: theme.color.surface, alignSelf: 'flex-start', borderBottomLeftRadius: 6, ...theme.shadow.card },
  action: { flexDirection: 'row', gap: 6, alignItems: 'center', backgroundColor: theme.color.ink, borderRadius: 999, paddingVertical: 9, paddingHorizontal: 14, alignSelf: 'flex-start' },
  actionText: { color: theme.color.onDark, fontWeight: '800', fontSize: theme.type.sm },
  meta: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  source: { marginTop: 8, borderLeftWidth: 3, borderLeftColor: theme.color.red, paddingLeft: 8 },
  sourceTitle: { fontWeight: '700', fontSize: theme.type.xs, color: theme.color.text },
  sourceText: { fontSize: theme.type.xs, color: theme.color.muted },
  chips: { gap: 8, paddingHorizontal: 12, paddingVertical: 8 },
  chip: { backgroundColor: theme.color.surface, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1, borderColor: theme.color.border },
  chipText: { color: theme.color.red, fontWeight: '700', fontSize: theme.type.sm },
  inputRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, alignItems: 'center' },
  input: { flex: 1, backgroundColor: theme.color.surface, borderRadius: 999, paddingHorizontal: 16, paddingVertical: 12, fontSize: theme.type.md, borderWidth: 1, borderColor: theme.color.border, color: theme.color.text },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.red, alignItems: 'center', justifyContent: 'center' },
});
