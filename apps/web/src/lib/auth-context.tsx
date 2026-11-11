"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiRequest, type AuthSession } from "./api";

interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
  login: (email: string, password: string, orgId?: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
    organization_slug: string;
  }) => Promise<void>;
  switchOrganization: (orgId: string) => Promise<void>;
  logout: () => void;
  hasPermission: (perm: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const STORAGE_KEY = "aegis.session.v1";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as AuthSession;
        setSession(parsed);
      }
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    } finally {
      setLoading(false);
    }
  }, []);

  const persistSession = useCallback((next: AuthSession | null) => {
    setSession(next);
    if (next) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const login = useCallback(
    async (email: string, password: string, orgId?: string) => {
      const data = await apiRequest<AuthSession>("/v1/auth/login", {
        method: "POST",
        body: { email, password, organization_id: orgId ?? null },
      });
      persistSession(data);
    },
    [persistSession],
  );

  const register = useCallback(
    async (payload: {
      email: string;
      password: string;
      full_name: string;
      organization_name: string;
      organization_slug: string;
    }) => {
      const data = await apiRequest<AuthSession>("/v1/auth/register", {
        method: "POST",
        body: payload,
      });
      persistSession(data);
    },
    [persistSession],
  );

  const switchOrganization = useCallback(
    async (orgId: string) => {
      if (!session) return;
      const me = await apiRequest<{
        user_id: string | null;
        email: string | null;
        full_name?: string;
        active_tenant_id: string;
        active_role?: string;
        role?: string;
        permissions: string[];
        organizations: AuthSession["organizations"];
      }>("/v1/auth/me", {
        token: session.access_token,
        orgId,
      });
      persistSession({
        ...session,
        active_tenant_id: me.active_tenant_id,
        active_role: me.active_role ?? me.role ?? session.active_role,
        permissions: me.permissions,
        organizations: me.organizations,
      });
    },
    [persistSession, session],
  );

  const logout = useCallback(() => {
    persistSession(null);
  }, [persistSession]);

  const hasPermission = useCallback(
    (perm: string) => Boolean(session?.permissions.includes(perm)),
    [session],
  );

  return (
    <AuthContext.Provider value={{ session, loading, login, register, switchOrganization, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
