import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  clearSession,
  loadSession,
  saveSession,
  setToken,
  setUnauthorizedHandler,
} from "./api";
import type { Session } from "./api";
import type { LoginResponse, User } from "./types";

interface AuthState {
  user: User | null;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string, name: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);

  const logout = useCallback(() => {
    clearSession();
    setToken(null);
    setSession(null);
  }, []);

  useEffect(() => setUnauthorizedHandler(logout), [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post<LoginResponse>("/api/auth/login", { email, password });
    const next = { token: res.access_token, user: res.user };
    saveSession(next, res.expires_in);
    setToken(next.token);
    setSession(next);
    return res.user;
  }, []);

  const register = useCallback(
    async (email: string, password: string, name: string) => {
      await api.post<User>("/api/auth/register", { email, password, name });
      return login(email, password);
    },
    [login],
  );

  const value = useMemo(
    () => ({ user: session?.user ?? null, login, register, logout }),
    [session, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
