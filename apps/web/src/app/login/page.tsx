"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React, { Suspense, useEffect, useState } from "react";
import { Eye, EyeOff, Mail, ShieldCheck, UserCheck } from "lucide-react";
import { apiRequest, ApiClientError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface InvitationInfo {
  token: string;
  organization_name?: string;
  email?: string;
  role?: string;
}

function LoginForm() {
  const { session, login, register } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const inviteParam = searchParams.get("invitation") || searchParams.get("token");
  const verifyParam = searchParams.get("verify") || searchParams.get("verify_email");

  const [mode, setMode] = useState<"login" | "register" | "invitation">(
    inviteParam ? "invitation" : "login",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(
    verifyParam ? "Please verify your email address to unlock all organization capabilities." : null,
  );

  // Invitation state
  const [invitation, setInvitation] = useState<InvitationInfo | null>(
    inviteParam ? { token: inviteParam } : null,
  );
  const [invitationLoading, setInvitationLoading] = useState(Boolean(inviteParam));

  useEffect(() => {
    if (session && !inviteParam) {
      router.replace("/dashboard");
    }
  }, [router, session, inviteParam]);

  useEffect(() => {
    if (!inviteParam) return;
    let isCancelled = false;

    async function inspectInvitation() {
      setInvitationLoading(true);
      try {
        const details = await apiRequest<{
          token?: string;
          organization_name?: string;
          email?: string;
          role?: string;
        }>(`/v1/orgs/invitations/${inviteParam}`);
        if (!isCancelled) {
          setInvitation({
            token: inviteParam,
            organization_name: details.organization_name || "Inviting Organization",
            email: details.email || "",
            role: details.role || "OPERATOR",
          });
          if (details.email) setEmail(details.email);
        }
      } catch {
        // Fallback gracefully if backend inspect route is unavailable
        if (!isCancelled) {
          setInvitation({
            token: inviteParam,
            organization_name: "AgentPay Nexus Workspace",
            role: "MEMBER",
          });
        }
      } finally {
        if (!isCancelled) setInvitationLoading(false);
      }
    }

    void inspectInvitation();
    return () => {
      isCancelled = true;
    };
  }, [inviteParam]);

  async function handleAcceptInvitation(e: React.FormEvent) {
    e.preventDefault();
    if (!invitation?.token) return;
    setErrorMsg(null);
    setSubmitting(true);
    try {
      await apiRequest(`/v1/orgs/invitations/${invitation.token}/accept`, {
        method: "POST",
        body: {
          email: email.trim(),
          password: password || undefined,
          full_name: fullName.trim() || undefined,
        },
      });
      // If user had credentials, log them in or redirect
      if (email && password) {
        try {
          await login(email.trim(), password);
        } catch {
          // If already session authenticated or requires manual login
        }
      }
      router.push("/dashboard");
    } catch (err) {
      setErrorMsg(
        err instanceof ApiClientError
          ? err.message
          : "Failed to accept invitation. The invitation may have expired or is invalid.",
      );
    } finally {
      setSubmitting(false);
    }
  }

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
      setErrorMsg(
        err instanceof ApiClientError
          ? err.message
          : "Authentication failed. Verify API connectivity.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
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

      {infoMsg && (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 flex items-start gap-2.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-xs text-sky-200"
        >
          <Mail className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" />
          <div className="flex-1">
            <span>{infoMsg}</span>
            <button
              type="button"
              onClick={() => setInfoMsg(null)}
              className="ml-2 font-medium underline hover:text-white"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {errorMsg && (
        <div
          role="alert"
          aria-live="assertive"
          className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          {errorMsg}
        </div>
      )}

      {mode === "invitation" ? (
        <div className="mt-6">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
            <div className="flex items-center gap-2 text-emerald-300">
              <UserCheck className="h-5 w-5" />
              <span className="text-sm font-semibold">Organization Invitation</span>
            </div>
            <p className="mt-1 text-xs text-slate-300">
              You have been invited to join{" "}
              <strong className="text-white">
                {invitation?.organization_name || "the organization"}
              </strong>
              {invitation?.role ? ` as ${invitation.role}` : ""}.
            </p>
          </div>

          <form onSubmit={(e) => void handleAcceptInvitation(e)} method="post" className="mt-5 space-y-4">
            <div>
              <label htmlFor="invite-email" className="block text-sm font-medium text-slate-200">
                Email Address <span aria-hidden="true">*</span>
              </label>
              <input
                id="invite-email"
                name="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
              />
            </div>

            <div>
              <label htmlFor="invite-full-name" className="block text-sm font-medium text-slate-200">
                Full Name
              </label>
              <input
                id="invite-full-name"
                name="full_name"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="invite-password" className="block text-sm font-medium text-slate-200">
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
                id="invite-password"
                name="password"
                type={showPassword ? "text" : "password"}
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Set or verify account password"
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3.5 py-2.5 text-sm text-white"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || invitationLoading}
              className="mt-2 w-full rounded-lg bg-emerald-500 py-2.5 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              {submitting ? "Joining Organization…" : "Accept Invitation & Join"}
            </button>

            <div className="text-center">
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setErrorMsg(null);
                }}
                className="text-xs text-slate-400 hover:text-white"
              >
                Return to standard sign in
              </button>
            </div>
          </form>
        </div>
      ) : (
        <>
          <div
            className="mt-6 grid grid-cols-2 gap-2 rounded-lg bg-aegis-bg p-1"
            role="tablist"
            aria-label="Authentication mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              onClick={() => {
                setMode("login");
                setErrorMsg(null);
              }}
              className={`rounded-md py-2 text-sm font-medium ${
                mode === "login"
                  ? "bg-aegis-panel text-white shadow"
                  : "text-slate-400 hover:text-white"
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
                mode === "register"
                  ? "bg-aegis-panel text-white shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Create Organization
            </button>
          </div>

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
                  <span className="mt-1 block text-xs text-slate-400">
                    Lowercase letters, numbers, and hyphens only.
                  </span>
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
        </>
      )}

      {/* Public links */}
      <div className="mt-6 border-t border-aegis-border pt-4 text-center text-[11px] text-slate-400">
        <a href="/status" className="hover:text-sky-300 hover:underline">
          System Status
        </a>
        <span className="mx-2">·</span>
        <a href="/legal/terms" className="hover:text-sky-300 hover:underline">
          Terms
        </a>
        <span className="mx-2">·</span>
        <a href="/legal/privacy" className="hover:text-sky-300 hover:underline">
          Privacy
        </a>
        <span className="mx-2">·</span>
        <a href="/legal/dpa" className="hover:text-sky-300 hover:underline">
          DPA
        </a>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-aegis-bg px-4 py-12 text-slate-100">
      <Suspense
        fallback={
          <div className="w-full max-w-md rounded-2xl border border-aegis-border bg-aegis-surface p-8 text-center text-slate-300">
            <ShieldCheck className="mx-auto h-8 w-8 text-sky-400" />
            <p className="mt-3 text-sm">Loading authentication…</p>
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
