import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, type LoginResponse } from '../api';
import { readSession, writeSession } from './tokenStore';

type Ctx = {
  ready: boolean;
  session: LoginResponse | null;
  signIn: (employeeId: string, lastName: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Persist the token + Sync Gateway session from /api/auth/refresh (sliding expiry). */
  renew: (patch: Partial<Pick<LoginResponse, 'token' | 'sync_gateway'>>) => Promise<void>;
  /** The backend rejected the stored session: sign out and tell the tech why. */
  expire: () => Promise<void>;
  notice: string | null;
};

const AuthContext = createContext<Ctx>({
  ready: false, session: null, signIn: async () => {}, signOut: async () => {}, renew: async () => {}, expire: async () => {}, notice: null,
});

/**
 * Sign-in = employee ID + last name. The backend answers with an app token
 * and a Sync Gateway session for this tech; the session is kept in the
 * Keychain so a tech who opens the app inside an equipment shelter, offline, lands
 * straight on their Couchbase Lite data.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Latest persisted session, including renewed tokens. Renewing doesn't call
  // setSession: that would restart the local database and sync for nothing.
  const latest = useRef<LoginResponse | null>(null);

  useEffect(() => {
    void (async () => {
      const raw = await readSession();
      if (raw) {
        try {
          latest.current = JSON.parse(raw);
          setSession(latest.current);
        } catch {
          /* corrupt - sign in again */
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = useCallback(async (employeeId: string, lastName: string) => {
    const res = await api<LoginResponse>('/api/auth/login', { body: { employee_id: employeeId.trim(), last_name: lastName.trim() } });
    await writeSession(JSON.stringify(res));
    latest.current = res;
    setNotice(null);
    setSession(res);
  }, []);

  const signOut = useCallback(async () => {
    await writeSession(null);
    latest.current = null;
    setSession(null);
  }, []);

  const renew = useCallback(async (patch: Partial<Pick<LoginResponse, 'token' | 'sync_gateway'>>) => {
    if (!latest.current) return;
    latest.current = { ...latest.current, ...Object.fromEntries(Object.entries(patch).filter(([, v]) => v != null)) };
    await writeSession(JSON.stringify(latest.current));
  }, []);

  const expire = useCallback(async () => {
    if (!latest.current) return;
    await writeSession(null);
    latest.current = null;
    setNotice('Your session expired - sign in again to see your route.');
    setSession(null);
  }, []);

  return <AuthContext.Provider value={{ ready, session, signIn, signOut, renew, expire, notice }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
