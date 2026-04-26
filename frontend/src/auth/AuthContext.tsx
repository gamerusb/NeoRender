import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { apiUrl } from "@/api";

// ── Types ────────────────────────────────────────────────────────────────────

export type UserRole = "admin" | "user";
export type UserPlan = "free" | "starter" | "pro" | "enterprise";

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  role: UserRole;
  plan: UserPlan;
  tenant_id: string;
  avatar_initials: string;
  created_at: string;
  plan_limits: {
    tasks_per_day: number;
    profiles: number;
    campaigns: number;
    storage_gb: number;
  };
  usage: {
    tasks_today: number;
    profiles_used: number;
    campaigns_used: number;
    storage_used_gb: number;
  };
}

interface AuthCtx {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

// ── Storage keys ─────────────────────────────────────────────────────────────

const TOKEN_KEY = "neo_auth_token";
const USER_KEY = "neo_auth_user";

function loadToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function saveToken(t: string | null): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* ignore */ }
}
function loadUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch { return null; }
}
function saveUser(u: AuthUser | null): void {
  try {
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
    else localStorage.removeItem(USER_KEY);
  } catch { /* ignore */ }
}

// ── Mock helpers (until real backend auth is ready) ──────────────────────────

const MOCK_USERS: AuthUser[] = [
  {
    id: 1,
    email: "admin@neorender.pro",
    name: "Admin",
    role: "admin",
    plan: "enterprise",
    tenant_id: "default",
    avatar_initials: "AD",
    created_at: "2025-01-01T00:00:00Z",
    plan_limits: { tasks_per_day: 9999, profiles: 999, campaigns: 999, storage_gb: 1000 },
    usage: { tasks_today: 12, profiles_used: 8, campaigns_used: 3, storage_used_gb: 4.2 },
  },
  {
    id: 2,
    email: "user@neorender.pro",
    name: "Demo User",
    role: "user",
    plan: "pro",
    tenant_id: "default",
    avatar_initials: "DU",
    created_at: "2025-03-15T00:00:00Z",
    plan_limits: { tasks_per_day: 100, profiles: 20, campaigns: 10, storage_gb: 50 },
    usage: { tasks_today: 34, profiles_used: 11, campaigns_used: 2, storage_used_gb: 12.8 },
  },
];

const MOCK_PASSWORDS: Record<string, string> = {
  "admin@neorender.pro": "admin123",
  "user@neorender.pro": "user123",
};

function mockLogin(email: string, password: string): { token: string; user: AuthUser } {
  const user = MOCK_USERS.find((u) => u.email === email);
  if (!user) throw new Error("Пользователь не найден");
  if (MOCK_PASSWORDS[email] !== password) throw new Error("Неверный пароль");
  const token = `mock_token_${user.id}_${Date.now()}`;
  return { token, user };
}

function mockRegister(name: string, email: string, _password: string): { token: string; user: AuthUser } {
  if (MOCK_USERS.find((u) => u.email === email)) {
    throw new Error("Email уже зарегистрирован");
  }
  const initials = name.split(" ").map((p) => p[0]?.toUpperCase() ?? "").join("").slice(0, 2) || "U";
  const newUser: AuthUser = {
    id: MOCK_USERS.length + 1,
    email,
    name,
    role: "user",
    plan: "free",
    tenant_id: "default",
    avatar_initials: initials,
    created_at: new Date().toISOString(),
    plan_limits: { tasks_per_day: 10, profiles: 3, campaigns: 1, storage_gb: 5 },
    usage: { tasks_today: 0, profiles_used: 0, campaigns_used: 0, storage_used_gb: 0 },
  };
  MOCK_USERS.push(newUser);
  MOCK_PASSWORDS[email] = _password;
  const token = `mock_token_${newUser.id}_${Date.now()}`;
  return { token, user: newUser };
}

// ── Real API helpers (используем когда бэкенд готов) ─────────────────────────

async function apiLogin(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(apiUrl("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json() as { status?: string; token?: string; user?: AuthUser; message?: string };
  if (!res.ok || data.status === "error") throw new Error(data.message || `HTTP ${res.status}`);
  return { token: data.token!, user: data.user! };
}

async function apiRegister(name: string, email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(apiUrl("/api/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
  const data = await res.json() as { status?: string; token?: string; user?: AuthUser; message?: string };
  if (!res.ok || data.status === "error") throw new Error(data.message || `HTTP ${res.status}`);
  return { token: data.token!, user: data.user! };
}

async function apiGetMe(token: string): Promise<AuthUser> {
  const res = await fetch(apiUrl("/api/auth/me"), {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json() as { status?: string; user?: AuthUser; message?: string };
  if (!res.ok || data.status === "error") throw new Error(data.message || `HTTP ${res.status}`);
  return data.user!;
}

// ── Detect if real backend auth exists ───────────────────────────────────────
// Если бэкенд отвечает на /api/auth/ping — используем реальный API.
// Если 404 или сеть недоступна — mock-режим.

let _useMock: boolean | null = null;

async function shouldUseMock(): Promise<boolean> {
  if (_useMock !== null) return _useMock;
  try {
    const res = await fetch(apiUrl("/api/auth/ping"), { method: "GET" });
    // Реальный бэкенд отвечает 200 с { auth: "real" }
    _useMock = res.status === 404;
  } catch {
    _useMock = true;
  }
  return _useMock;
}

// ── Context ───────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(loadUser);
  const [token, setToken] = useState<string | null>(loadToken);
  const [isLoading, setIsLoading] = useState(false);

  // Persist to localStorage on change
  useEffect(() => { saveToken(token); }, [token]);
  useEffect(() => { saveUser(user); }, [user]);

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const useMock = await shouldUseMock();
      const { token: t, user: u } = useMock
        ? mockLogin(email, password)
        : await apiLogin(email, password);
      setToken(t);
      setUser(u);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    setIsLoading(true);
    try {
      const useMock = await shouldUseMock();
      const { token: t, user: u } = useMock
        ? mockRegister(name, email, password)
        : await apiRegister(name, email, password);
      setToken(t);
      setUser(u);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    if (!token) return;
    try {
      const useMock = await shouldUseMock();
      if (!useMock) {
        const u = await apiGetMe(token);
        setUser(u);
      }
    } catch {
      // token expired — logout
      setToken(null);
      setUser(null);
    }
  }, [token]);

  const value = useMemo<AuthCtx>(
    () => ({
      user,
      token,
      isLoading,
      isAuthenticated: Boolean(user && token),
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, token, isLoading, login, register, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth must be used inside AuthProvider");
  return c;
}
