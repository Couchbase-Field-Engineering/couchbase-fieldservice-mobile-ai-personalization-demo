import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { DataProvider } from '@/src/data/DataContext';
import { AuthProvider } from '@/src/session/AuthContext';
import { theme } from '@/src/theme';
import { DeviceFrame } from '@/src/ui/DeviceFrame';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <DataProvider>
          <DeviceFrame>
            <StatusBar style="light" />
            <Stack
              screenOptions={{
                headerStyle: { backgroundColor: theme.color.surface },
                headerTintColor: theme.color.ink,
                headerTitleStyle: { fontWeight: '800' },
                headerShadowVisible: false,
                contentStyle: { backgroundColor: theme.color.bg },
              }}
            >
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="login" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="site" options={{ title: 'Site', presentation: 'modal' }} />
              <Stack.Screen name="workorder" options={{ title: 'Work order', presentation: 'modal' }} />
              <Stack.Screen name="visit" options={{ title: 'Log visit', presentation: 'modal' }} />
              <Stack.Screen name="confirm" options={{ title: 'Review & submit', presentation: 'modal' }} />
            </Stack>
          </DeviceFrame>
        </DataProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
