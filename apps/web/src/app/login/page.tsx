"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React, { Suspense, useEffect, useState } from "react";
import { Eye, EyeOff, Mail, ShieldCheck, UserCheck, ArrowRight } from "lucide-react";
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
        }
      } catch {
        if (!isCancelled) {
          setErrorMsg("Invitation invalid or expired.");
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
      if (email && password) {
        try {
          await login(email.trim(), password);
        } catch {
          // fallback if already authenticated
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
          : "Authentication failed. Verify API connectivity and credentials.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-md border border-aegis-border bg-aegis-surface p-8 shadow-panel rounded-sm">
      {/* Brand Header */}
      <div className="flex items-center justify-between border-b border-aegis-border pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center border border-aegis-accent/40 bg-aegis-accent/10 text-aegis-accent">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-base font-bold tracking-wider text-aegis-text-primary">AEGIS</span>
              <span className="border border-aegis-border bg-aegis-card px-1.5 py-0.2 font-mono text-[9px] uppercase text-aegis-text-muted">
                CONSOLE
              </span>
            </div>
            <p className="font-mono text-[10px] text-aegis-text-faint tracking-tight">OPERATOR ACCESS CONTROL</p>
          </div>
        </div>
        <div className="font-mono text-[10px] text-aegis-accent uppercase tracking-widest font-semibold">
          SECURE GATEWAY
        </div>
      </div>

      {infoMsg && (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 flex items-start gap-2.5 border border-aegis-border bg-aegis-card p-3 font-mono text-xs text-aegis-text-muted"
        >
          <Mail className="mt-0.5 h-3.5 w-3.5 shrink-0 text-aegis-accent" />
          <div className="flex-1">
            <span>{infoMsg}</span>
            <button
              type="button"
              onClick={() => setInfoMsg(null)}
              className="ml-2 font-semibold text-aegis-accent underline hover:text-white"
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
          className="mt-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]"
        >
          {errorMsg}
        </div>
      )}

      {mode === "invitation" ? (
        <div className="mt-6">
          <div className="border border-[#3A4A28] bg-[#162112] p-3.5 font-mono text-xs text-aegis-text-muted">
            <div className="flex items-center gap-2 text-aegis-accent font-semibold uppercase tracking-wider text-[11px]">
              <UserCheck className="h-4 w-4" />
              <span>ORGANIZATION INVITATION DETECTED</span>
            </div>
            <p className="mt-1.5 text-xs text-aegis-text-primary">
              Invited to join <strong className="text-white">{invitation?.organization_name || "the organization"}</strong>
              {invitation?.role ? ` as [${invitation.role}]` : ""}.
            </p>
          </div>

          <form onSubmit={(e) => void handleAcceptInvitation(e)} method="post" className="mt-5 space-y-4">
            <div>
              <label htmlFor="invite-email" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                Email Address <span aria-hidden="true" className="text-aegis-accent">*</span>
              </label>
              <input
                id="invite-email"
                name="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@institution.com"
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="invite-full-name" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                Operator Full Name
              </label>
              <input
                id="invite-full-name"
                name="full_name"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Alex Morgan"
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="invite-password" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                  Account Password <span aria-hidden="true" className="text-aegis-accent">*</span>
                </label>
                <button
                  type="button"
                  aria-pressed={showPassword}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="inline-flex items-center gap-1 font-mono text-[10px] uppercase text-aegis-text-muted hover:text-aegis-accent"
                >
                  {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
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
                placeholder="Minimum 8 characters"
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || invitationLoading}
              className="mt-2 w-full border border-aegis-accent bg-aegis-accent py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors"
            >
              {submitting ? "Accepting Credentials…" : "Accept Invitation & Enter"}
            </button>

            <div className="text-center pt-2">
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setErrorMsg(null);
                }}
                className="font-mono text-xs text-aegis-text-muted hover:text-aegis-text-primary underline"
              >
                Return to standard sign in
              </button>
            </div>
          </form>
        </div>
      ) : (
        <>
          {/* Authentication Mode Switcher */}
          <div
            className="mt-6 grid grid-cols-2 gap-1 border border-aegis-border bg-aegis-card p-1"
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
              className={`py-1.5 font-mono text-xs uppercase tracking-wider transition-colors ${
                mode === "login"
                  ? "border border-aegis-accent bg-aegis-secondary font-bold text-aegis-accent"
                  : "text-aegis-text-muted hover:text-aegis-text-primary"
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
              className={`py-1.5 font-mono text-xs uppercase tracking-wider transition-colors ${
                mode === "register"
                  ? "border border-aegis-accent bg-aegis-secondary font-bold text-aegis-accent"
                  : "text-aegis-text-muted hover:text-aegis-text-primary"
              }`}
            >
              New Tenant
            </button>
          </div>

          <form onSubmit={(e) => void handleSubmit(e)} method="post" className="mt-6 space-y-4">
            {mode === "register" && (
              <>
                <div>
                  <label htmlFor="full-name" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                    Operator Full Name <span aria-hidden="true" className="text-aegis-accent">*</span>
                  </label>
                  <input
                    id="full-name"
                    name="full_name"
                    type="text"
                    required
                    autoComplete="name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Alex Morgan"
                    className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="org-name" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                    Organization Name <span aria-hidden="true" className="text-aegis-accent">*</span>
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
                    placeholder="Acme Financial Technologies"
                    className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                  />
                </div>

                <div>
                  <label htmlFor="org-slug" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                    Organization Slug <span aria-hidden="true" className="text-aegis-accent">*</span>
                  </label>
                  <input
                    id="org-slug"
                    name="organization_slug"
                    type="text"
                    required
                    pattern={"^[a-z0-9\\-]+$"}
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    value={orgSlug}
                    onChange={(e) => setOrgSlug(e.target.value)}
                    placeholder="acme-fintech"
                    className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
                  />
                </div>
              </>
            )}

            <div>
              <label htmlFor="email" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                Operator Email <span aria-hidden="true" className="text-aegis-accent">*</span>
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
                placeholder="operator@institution.com"
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="block font-mono text-xs uppercase tracking-wider text-aegis-text-muted">
                  Password <span aria-hidden="true" className="text-aegis-accent">*</span>
                </label>
                <button
                  type="button"
                  aria-pressed={showPassword}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="inline-flex items-center gap-1 font-mono text-[10px] uppercase text-aegis-text-muted hover:text-aegis-accent"
                >
                  {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
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
                placeholder="Enter password"
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="mt-3 w-full border border-aegis-accent bg-aegis-accent py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors shadow-editorial flex items-center justify-center gap-2"
            >
              <span>{submitting ? "Authenticating…" : mode === "login" ? "Enter Control Console" : "Provision Organization & Enter"}</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </form>
        </>
      )}

      {/* Public footer links */}
      <div className="mt-8 border-t border-aegis-border pt-4 text-center font-mono text-[10px] text-aegis-text-faint flex items-center justify-center gap-4">
        <a href="/status" className="hover:text-aegis-accent transition-colors">
          STATUS
        </a>
        <span>•</span>
        <a href="/legal/terms" className="hover:text-aegis-text-primary transition-colors">
          TERMS
        </a>
        <span>•</span>
        <a href="/legal/privacy" className="hover:text-aegis-text-primary transition-colors">
          PRIVACY
        </a>
        <span>•</span>
        <a href="/legal/dpa" className="hover:text-aegis-text-primary transition-colors">
          DPA
        </a>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-aegis-bg px-4 py-12 text-aegis-text-primary bg-financial-grid bg-financial-radial selection:bg-aegis-accent selection:text-aegis-bg">
      <Suspense
        fallback={
          <div className="w-full max-w-md border border-aegis-border bg-aegis-surface p-8 text-center font-mono text-xs text-aegis-text-muted shadow-panel">
            <ShieldCheck className="mx-auto h-6 w-6 text-aegis-accent animate-pulse" />
            <p className="mt-3">VERIFYING OPERATOR CREDENTIALS…</p>
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
