"use client";

import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";
import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import { ApiClientError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const { session, login, register } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      router.replace("/dashboard");
    }
  }, [router, session]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email.trim(), password);
      } else {
        await register({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          organization_name: orgName.trim(),
          organization_slug: orgSlug.trim().toLowerCase(),
        });
      }
      router.push("/dashboard");
    } catch (err) {
      setErrorMsg(err instanceof ApiClientError ? err.message : "Authentication failed. Verify API connectivity.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-aegis-bg px-4 py-12 text-slate-100">
      <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-surface p-8 shadow-2xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-400 ring-1 ring-sky-400/30">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">AEGIS Control Plane</h1>
            <p className="text-xs text-slate-400">Multi-tenant financial governance</p>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-2 rounded-lg bg-aegis-bg p-1" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            onClick={() => {
              setMode("login");
              setErrorMsg(null);
            }}
            className={`rounded-md py-2 text-sm font-medium ${
              mode === "login" ? "bg-aegis-panel text-white shadow" : "text-slate-400 hover:text-white"
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            onClick={() => {
              setMode("register");
              setErrorMsg(null);
            }}
            className={`rounded-md py-2 text-sm font-medium ${
              mode === "register" ? "bg-aegis-panel text-white shadow" : "text-slate-400 hover:text-white"
            }`}
          >
            Create Organization
          </button>
        </div>

        {errorMsg && (
          <div
            role="status"
            aria-live="polite"
            className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
          >
            {errorMsg}
          </div>
        )}

        <form onSubmit={(e) => void handleSubmit(e)} method="post" className="mt-6 space-y-4">
          {mode === "register" && (
            <>
              <div>
                <label htmlFor="full-name" className="block text-sm font-medium text-slate-200">
                  Full Name <span aria-hidden="true">*</span>
                </label>
                <input
                  id="full-name"
                  name="full_name"
                  type="text"
                  required
                  autoComplete="name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
                />
              </div>

              <div>
                <label htmlFor="org-name" className="block text-sm font-medium text-slate-200">
                  Organization Name <span aria-hidden="true">*</span>
                </label>
                <input
                  id="org-name"
                  name="organization_name"
                  type="text"
                  required
                  minLength={2}
                  value={orgName}
                  onChange={(e) => {
                    const next = e.target.value;
                    setOrgName(next);
                    if (!orgSlug) {
                      setOrgSlug(
                        next
                          .toLowerCase()
                          .replace(/[^a-z0-9]+/g, "-")
                          .replace(/^-|-$/g, ""),
                      );
                    }
                  }}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
                />
              </div>

              <div>
                <label htmlFor="org-slug" className="block text-sm font-medium text-slate-200">
                  Organization Slug <span aria-hidden="true">*</span>
                </label>
                <input
                  id="org-slug"
                  name="organization_slug"
                  type="text"
                  required
                  pattern="^[a-z0-9-]+$"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={orgSlug}
                  onChange={(e) => setOrgSlug(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
                />
                <span className="mt-1 block text-xs text-slate-400">Lowercase letters, numbers, and hyphens only.</span>
              </div>
            </>
          )}

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-200">
              Email <span aria-hidden="true">*</span>
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="username"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
            />
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label htmlFor="password" className="block text-sm font-medium text-slate-200">
                Password <span aria-hidden="true">*</span>
              </label>
              <button
                type="button"
                aria-pressed={showPassword}
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword((prev) => !prev)}
                className="inline-flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300"
              >
                {showPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                <span>{showPassword ? "Hide" : "Show"}</span>
              </button>
            </div>
            <input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              required
              minLength={mode === "register" ? 8 : 1}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
            />
            {mode === "register" && (
              <span className="mt-1 block text-xs text-slate-400">Minimum 8 characters.</span>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
          >
            {submitting
              ? "Authenticating…"
              : mode === "login"
                ? "Sign In to Organization"
                : "Create Organization & Continue"}
          </button>
        </form>
      </div>
    </div>
  );
}
