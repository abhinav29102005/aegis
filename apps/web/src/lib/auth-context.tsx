"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiRequest, ApiClientError, type AuthSession } from "./api";

interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string, orgId?: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    organization_name: string;
    organization_slug: string;
  }) => Promise<void>;
  switchOrganization: (orgId: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
  hasPermission: (perm: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const checkSession = useCallback(async () => {
    try {
      const data = await apiRequest<AuthSession>("/api/auth/me", {
        timeoutMs: 10000,
      });
      setSession(data);
      setError(null);
    } catch (err) {
      // 401 or invalid session -> evict and redirect cleanly to /login
      setSession(null);
      if (err instanceof ApiClientError && err.status === 401) {
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          const next = encodeURIComponent(window.location.pathname + window.location.search);
          window.location.href = `/login?next=${next}`;
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void checkSession();
  }, [checkSession]);

  const login = useCallback(
    async (email: string, password: string, orgId?: string) => {
      setError(null);
      try {
        const data = await apiRequest<AuthSession>("/api/auth/login", {
          method: "POST",
          body: { email, password, organization_id: orgId ?? null },
          timeoutMs: 15000,
        });
        setSession(data);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Authentication failed";
        setError(msg);
        throw err;
      }
    },
    [],
  );

  const register = useCallback(
    async (payload: {
      email: string;
      password: string;
      full_name: string;
      organization_name: string;
      organization_slug: string;
    }) => {
      setError(null);
      try {
        const data = await apiRequest<AuthSession>("/api/auth/signup", {
          method: "POST",
          body: payload,
          timeoutMs: 15000,
        });
        setSession(data);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Registration failed";
        setError(msg);
        throw err;
      }
    },
    [],
  );

  const switchOrganization = useCallback(
    async (orgId: string) => {
      setError(null);
      try {
        const data = await apiRequest<AuthSession>("/api/auth/switch-org", {
          method: "POST",
          body: { organization_id: orgId },
          timeoutMs: 15000,
        });
        setSession(data);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to switch organization";
        setError(msg);
        throw err;
      }
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await apiRequest("/api/auth/logout", { method: "POST", timeoutMs: 5000 });
    } catch {
      // ignore
    } finally {
      setSession(null);
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const hasPermission = useCallback(
    (perm: string) => {
      if (!session) return false;
      if (session.active_role === "OWNER" || session.active_role === "ADMIN") return true;
      return session.permissions?.includes(perm) ?? false;
    },
    [session],
  );

  return (
    <AuthContext.Provider
      value={{
        session,
        loading,
        error,
        login,
        register,
        switchOrganization,
        logout,
        clearError,
        hasPermission,
      }}
    >
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="fixed top-4 right-4 z-50 flex max-w-md items-center justify-between gap-3 rounded-xl border border-rose-500/40 bg-rose-950/95 px-4 py-3 text-sm text-rose-200 shadow-2xl backdrop-blur transition-all"
        >
          <div className="flex items-center gap-2">
            <span className="font-semibold text-rose-400">Error:</span>
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={clearError}
            className="rounded p-1 text-rose-400 hover:bg-rose-900/60 hover:text-rose-100"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
