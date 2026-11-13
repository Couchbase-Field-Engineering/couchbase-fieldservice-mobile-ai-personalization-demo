import { Platform, type ViewStyle } from 'react-native';

/**
 * Couchbase palette: Couchbase red on white, with the near-black the brand
 * uses for dark surfaces and its wordmark. The logo files in assets/images
 * are the official Couchbase mark and wordmark, unmodified.
 */
const shadowCard: ViewStyle = Platform.select({
  ios: { shadowColor: '#14151A', shadowOpacity: 0.1, shadowRadius: 14, shadowOffset: { width: 0, height: 6 } },
  android: { elevation: 3 },
  default: { boxShadow: '0 6px 18px rgba(20,21,26,0.10)' } as ViewStyle,
}) as ViewStyle;

export const theme = {
  color: {
    red: '#EA2328',
    redDark: '#B8141A',
    redSoft: '#FDECEC',
    ink: '#14151A',
    inkDeep: '#0B0C10',
    slate: '#2E3038',
    bg: '#F3F4F6',
    surface: '#FFFFFF',
    text: '#14151A',
    muted: '#5B5E69',
    faint: '#9A9DA8',
    border: '#E3E5EA',
    ok: '#12805C',
    okSoft: '#E3F5EE',
    warn: '#A85D00',
    warnSoft: '#FFF2DD',
    danger: '#B8141A',
    dangerSoft: '#FDECEC',
    info: '#1B5FC4',
    infoSoft: '#E7EFFC',
    onDark: '#FFFFFF',
    onDarkMuted: 'rgba(255,255,255,0.72)',
  },
  gradient: {
    hero: ['#0B0C10', '#2A2C35'] as const,
    ink: ['#0B0C10', '#2E3038'] as const,
    site: ['#14151A', '#3A3D48'] as const,
    workorder: ['#B8141A', '#EA2328'] as const,
    alarm: ['#7A3E00', '#A85D00'] as const,
    ok: ['#0B5C41', '#12805C'] as const,
  },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  type: { xs: 11, sm: 13, md: 15, lg: 17, xl: 20, title: 26, hero: 34 },
  radius: 16,
  radiusSm: 10,
  shadow: { card: shadowCard },
} as const;

export type GradientKey = keyof typeof theme.gradient;
