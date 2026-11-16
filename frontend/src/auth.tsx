import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import * as api from "./api";

const STORAGE_KEY = "mockmate.auth";

type Stored = { token: string; expiresAt: string; user: api.User };

type AuthState = {
  user: api.User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  guest: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

function readStored(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Stored;
    return new Date(stored.expiresAt) > new Date() ? stored : null;
  } catch {
    return null;
  }
}

function writeStored(value: Stored | null) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode): stay logged in for this tab only */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState<Stored | null>(() => {
    const s = readStored();
    api.setAuthToken(s?.token ?? null);
    return s;
  });

  const save = useCallback((res: api.TokenResponse | null) => {
    const value = res ? { token: res.access_token, expiresAt: res.expires_at, user: res.user } : null;
    api.setAuthToken(value?.token ?? null);
    writeStored(value);
    setStored(value);
  }, []);

  const logout = useCallback(() => save(null), [save]);

  useEffect(() => {
    api.setUnauthorizedHandler(logout); // expired or revoked token -> back to login
    return () => api.setUnauthorizedHandler(null);
  }, [logout]);

  const value = useMemo<AuthState>(
    () => ({
      user: stored?.user ?? null,
      ready: true,
      login: async (email, password) => save(await api.login(email, password)),
      register: async (email, password, name) => save(await api.register(email, password, name)),
      guest: async () => save(await api.loginAsGuest()),
      logout,
    }),
    [stored, save, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (admin && !user.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}
