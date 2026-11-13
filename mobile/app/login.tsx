import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { Redirect } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { api, type Persona } from '@/src/api';
import { API_URL } from '@/src/config';
import { useAuth } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { Button, Pill, Wordmark } from '@/src/ui/components';

const FALLBACK: Persona[] = [
  { tech_id: 'T1001', name: 'Maya Chen', last_name: 'Chen', employee_id: '204817', area: 'Boston North Shore', stops_today: 5, sites: 57, blurb: 'A critical tower with a failing battery string, a steel shelter with no signal and a work order that needs a budget override.' },
  { tech_id: 'T1002', name: 'Devon Walker', last_name: 'Walker', employee_id: '318552', area: 'Hudson Valley', stops_today: 4, sites: 48, blurb: 'A mountaintop microwave relay with a degraded link and no coverage on the access road.' },
  { tech_id: 'T1003', name: 'Sofia Alvarez', last_name: 'Alvarez', employee_id: '427190', area: 'Dallas-Fort Worth', stops_today: 5, sites: 52, blurb: 'A 12-node stadium small-cell cluster on one hub SLA, plus a rooftop on an access hold.' },
];

export default function Login() {
  const { session, signIn, notice } = useAuth();
  const insets = useSafeAreaInsets();
  const [emp, setEmp] = useState('');
  const [last, setLast] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [personas, setPersonas] = useState<Persona[]>(FALLBACK);

  useEffect(() => {
    api<{ personas: Persona[] }>('/api/demo/personas', { timeoutMs: 5000 })
      .then((r) => r.personas.length && setPersonas(r.personas))
      .catch(() => {});
  }, []);

  if (session) return <Redirect href="/(tabs)" />;

  const go = async (e = emp, l = last) => {
    setBusy(true);
    setErr(null);
    try {
      await signIn(e, l);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <LinearGradient colors={theme.gradient.hero as unknown as [string, string]} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={[styles.wrap, { paddingTop: insets.top + 32, paddingBottom: insets.bottom + 24 }]} keyboardShouldPersistTaps="handled">
          <Wordmark size={17} />
          <Text style={styles.hero}>Every site,{'\n'}ready before you open the gate.</Text>
          <Text style={styles.sub}>Sign in to see today's sites, each one's alarms and work plan from the asset-health model, and close out work orders from inside the shelter - with or without signal.</Text>

          <View style={styles.form}>
            {notice ? (
              <View style={styles.notice}>
                <Ionicons name="time-outline" size={16} color={theme.color.ink} />
                <Text style={styles.noticeText}>{notice}</Text>
              </View>
            ) : null}
            <Text style={styles.label}>EMPLOYEE ID</Text>
            <TextInput value={emp} onChangeText={setEmp} placeholder="e.g. 204817" placeholderTextColor={theme.color.faint} style={styles.input} keyboardType="number-pad" />
            <Text style={styles.label}>LAST NAME</Text>
            <TextInput value={last} onChangeText={setLast} placeholder="e.g. Chen" placeholderTextColor={theme.color.faint} style={styles.input} autoCapitalize="words" />
            {err ? <Text style={styles.err}>{err}</Text> : null}
            <Button label="Start my day" onPress={() => void go()} busy={busy} disabled={!emp || !last} icon="log-in-outline" />
          </View>

          <Text style={[styles.label, { color: theme.color.onDarkMuted, marginTop: 28 }]}>DEMO TECHNICIANS · FROM TODAY'S DATABRICKS EXPORT</Text>
          {personas.map((p) => (
            <Pressable key={p.tech_id} onPress={() => void go(p.employee_id, p.last_name)} style={({ pressed }) => [styles.persona, pressed && { opacity: 0.8 }]}>
              <View style={styles.avatar}>
                <Text style={{ color: theme.color.red, fontWeight: '900' }}>{p.name.split(' ').map((s) => s[0]).join('')}</Text>
              </View>
              <View style={{ flex: 1, gap: 3 }}>
                <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Text style={styles.pname}>{p.name}</Text>
                  <Pill label={`${p.stops_today} stops today`} tone="dark" />
                </View>
                <Text style={styles.pmeta}>{p.area} · {p.sites} sites · #{p.employee_id}</Text>
                <Text style={styles.pblurb}>{p.blurb}</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={theme.color.onDarkMuted} />
            </Pressable>
          ))}
          <Text style={styles.foot}>Backend: {API_URL}</Text>
        </ScrollView>
      </LinearGradient>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 22, gap: 10, maxWidth: 520, width: '100%', alignSelf: 'center' },
  hero: { color: theme.color.onDark, fontSize: theme.type.hero, fontWeight: '900', marginTop: 28, lineHeight: 40 },
  sub: { color: theme.color.onDarkMuted, fontSize: theme.type.md, lineHeight: 21 },
  form: { backgroundColor: theme.color.surface, borderRadius: theme.radius, padding: 18, gap: 8, marginTop: 18 },
  label: { color: theme.color.muted, fontSize: theme.type.xs, fontWeight: '800', letterSpacing: 1.3 },
  input: { borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radiusSm, padding: 13, fontSize: theme.type.lg, color: theme.color.text, marginBottom: 6 },
  err: { color: theme.color.danger, fontWeight: '600' },
  notice: { flexDirection: 'row', gap: 8, alignItems: 'center', backgroundColor: theme.color.warnSoft, borderRadius: theme.radiusSm, padding: 10, marginBottom: 6 },
  noticeText: { flex: 1, color: theme.color.ink, fontWeight: '600', fontSize: theme.type.sm },
  persona: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.10)', borderRadius: theme.radius, padding: 14, borderWidth: 1, borderColor: 'rgba(255,255,255,0.16)' },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: theme.color.onDark, alignItems: 'center', justifyContent: 'center' },
  pname: { color: theme.color.onDark, fontWeight: '800', fontSize: theme.type.md },
  pmeta: { color: theme.color.onDarkMuted, fontSize: theme.type.sm },
  pblurb: { color: 'rgba(255,255,255,0.9)', fontSize: theme.type.sm },
  foot: { color: 'rgba(255,255,255,0.5)', fontSize: theme.type.xs, marginTop: 16, textAlign: 'center' },
});
