"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type AgentRecord, type MerchantRecord, type PassportRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency, truncateId } from "@/lib/format";

export default function PassportsPage() {
  const { session, hasPermission } = useAuth();
  const [passports, setPassports] = useState<PassportRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [merchants, setMerchants] = useState<MerchantRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<PassportRecord | null>(null);

  // Search & Pagination states
  const [searchQuery, setSearchQuery] = useState("");
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);

  // Issue new passport states
  const [agentId, setAgentId] = useState("");
  const [totalDollars, setTotalDollars] = useState("100.00");
  const [perTxDollars, setPerTxDollars] = useState("50.00");
  const [dailyDollars, setDailyDollars] = useState("100.00");
  const [thresholdDollars, setThresholdDollars] = useState("30.00");
  const [allowUnknownMerchants, setAllowUnknownMerchants] = useState(false);
  const [selectedMerchantIds, setSelectedMerchantIds] = useState<string[]>([]);
  const [categories, setCategories] = useState("SOFTWARE");

  // Inline PATCH Policy Editor modal state
  const [editingPassport, setEditingPassport] = useState<PassportRecord | null>(null);
  const [editPerTxDollars, setEditPerTxDollars] = useState("");
  const [editDailyDollars, setEditDailyDollars] = useState("");
  const [editThresholdDollars, setEditThresholdDollars] = useState("");
  const [editAllowUnknown, setEditAllowUnknown] = useState(false);
  const [editCategories, setEditCategories] = useState("");
  const [savingPolicy, setSavingPolicy] = useState(false);

  // Helper conversion
  const toMinor = (val: string) => Math.max(0, Math.round(Number.parseFloat(val || "0") * 100));

  const loadData = useCallback(async () => {
    if (!session) return;
    setError(null);
    try {
      const qs = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (searchQuery.trim()) qs.set("q", searchQuery.trim());

      const [p, a, m] = await Promise.all([
        apiRequest<PassportRecord[]>(`/v1/guardian/passports?${qs.toString()}`, {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<AgentRecord[]>("/v1/guardian/agents", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
        apiRequest<MerchantRecord[]>("/v1/guardian/merchants", {
          token: session.access_token,
          orgId: session.active_tenant_id,
        }),
      ]);
      setPassports(p);
      setAgents(a);
      setMerchants(m);
      setAgentId((curr) => curr || (a[0]?.id ?? ""));
      setSelectedMerchantIds((curr) => (curr.length === 0 && m[0] ? [m[0].id] : curr));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load passports");
    }
  }, [limit, offset, searchQuery, session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const agentNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of agents) {
      map.set(a.id, a.name);
    }
    return map;
  }, [agents]);

  // Client-side filtering across fields
  const filteredPassports = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return passports;
    return passports.filter((p) => {
      const agentName = (agentNameById.get(p.agent_id) ?? "").toLowerCase();
      return (
        p.id.toLowerCase().includes(q) ||
        p.agent_id.toLowerCase().includes(q) ||
        p.status.toLowerCase().includes(q) ||
        p.currency.toLowerCase().includes(q) ||
        agentName.includes(q)
      );
    });
  }, [passports, searchQuery, agentNameById]);

  const pagedPassports = useMemo(() => {
    return filteredPassports.slice(offset, offset + limit);
  }, [filteredPassports, offset, limit]);

  async function handleRevoke(passport: PassportRecord) {
    if (!session) return;
    try {
      await apiRequest(`/v1/guardian/passports/${passport.id}/revoke`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setNotice(`Revoked passport ${truncateId(passport.id)}.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke passport");
    } finally {
      setConfirmRevoke(null);
    }
  }

  async function handleCreatePassport(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    setNotice(null);
    try {
      await apiRequest("/v1/guardian/passports", {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
        body: {
          agent_id: agentId,
          policy_version: "policy-v1",
          currency: "USD",
          total_budget_minor: toMinor(totalDollars),
          per_tx_limit_minor: toMinor(perTxDollars),
          daily_limit_minor: toMinor(dailyDollars),
          human_approval_threshold_minor: toMinor(thresholdDollars),
          allowed_merchant_ids: selectedMerchantIds,
          allowed_categories: categories
            .split(",")
            .map((c) => c.trim().toUpperCase())
            .filter(Boolean),
          allow_unknown_merchants: allowUnknownMerchants,
          expires_in_days: 30,
        },
      });
      setNotice("Spending passport issued successfully.");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to issue spending passport");
    }
  }

  function openEditPolicyModal(p: PassportRecord) {
    setEditingPassport(p);
    setEditPerTxDollars((p.per_tx_limit_minor / 100).toFixed(2));
    setEditDailyDollars((p.daily_limit_minor / 100).toFixed(2));
    setEditThresholdDollars((p.human_approval_threshold_minor / 100).toFixed(2));
    setEditAllowUnknown(p.allow_unknown_merchants);
    setEditCategories(p.allowed_categories?.join(", ") ?? "");
  }

  async function handleSavePolicy(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !editingPassport) return;
    setSavingPolicy(true);
    setError(null);
    setNotice(null);

    const patchBody = {
      per_tx_limit_minor: toMinor(editPerTxDollars),
      daily_limit_minor: toMinor(editDailyDollars),
      human_approval_threshold_minor: toMinor(editThresholdDollars),
      allow_unknown_merchants: editAllowUnknown,
      allowed_categories: editCategories
        .split(",")
        .map((c) => c.trim().toUpperCase())
        .filter(Boolean),
    };

    try {
      try {
        await apiRequest(`/v1/guardian/passports/${editingPassport.id}/policy`, {
          method: "PATCH",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: patchBody,
        });
      } catch {
        await apiRequest(`/v1/guardian/passports/${editingPassport.id}`, {
          method: "PATCH",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: patchBody,
        });
      }
      setNotice(`Updated policy limits for passport ${truncateId(editingPassport.id)}.`);
      setEditingPassport(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update passport policy");
    } finally {
      setSavingPolicy(false);
    }
  }

  return (
    <AppShell
      title="Spending Passports & Policy Controls"
      subtitle="Deterministic policy limits, per-transaction velocity ceilings, and row-locked budget reservations."
    >
      {error && (
        <div role="alert" className="mb-4 border border-[#4A2828] bg-[#211212] p-3 font-mono text-xs text-[#EF5350]">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-4 border border-[#3A4A28] bg-[#162112] p-3 font-mono text-xs text-aegis-accent">
          {notice}
        </div>
      )}

      {/* Issue Passport Panel */}
      {hasPermission("passports:write") && (
        <form onSubmit={handleCreatePassport} className="mb-8 border border-aegis-border bg-aegis-surface p-5 rounded-sm">
          <div className="flex items-center justify-between border-b border-aegis-border pb-3">
            <div>
              <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                POLICY DEFINITION
              </span>
              <h2 className="mt-0.5 text-sm font-semibold text-aegis-text-primary">Issue New Spending Passport</h2>
            </div>
            <span className="font-mono text-[10px] text-aegis-text-faint">ENGINE: DETERMINISTIC V1</span>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 font-mono">
            <div>
              <label htmlFor="pp-agent" className="block text-xs uppercase text-aegis-text-muted">
                Target AI Agent <span className="text-aegis-accent">*</span>
              </label>
              <select
                id="pp-agent"
                required
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id} className="bg-aegis-surface">
                    {a.name} [{a.status}]
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="pp-total" className="block text-xs uppercase text-aegis-text-muted">
                Total Budget (USD)
              </label>
              <input
                id="pp-total"
                type="number"
                step="0.01"
                min="0"
                required
                value={totalDollars}
                onChange={(e) => setTotalDollars(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="pp-pertx" className="block text-xs uppercase text-aegis-text-muted">
                Per-Transaction Limit (USD)
              </label>
              <input
                id="pp-pertx"
                type="number"
                step="0.01"
                min="0"
                required
                value={perTxDollars}
                onChange={(e) => setPerTxDollars(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="pp-daily" className="block text-xs uppercase text-aegis-text-muted">
                Daily Limit (USD)
              </label>
              <input
                id="pp-daily"
                type="number"
                step="0.01"
                min="0"
                required
                value={dailyDollars}
                onChange={(e) => setDailyDollars(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="pp-thresh" className="block text-xs uppercase text-aegis-text-muted">
                Human Approval Threshold (USD)
              </label>
              <input
                id="pp-thresh"
                type="number"
                step="0.01"
                min="0"
                required
                value={thresholdDollars}
                onChange={(e) => setThresholdDollars(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary tabular-nums focus:border-aegis-accent focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="pp-cats" className="block text-xs uppercase text-aegis-text-muted">
                Allowed Categories (CSV)
              </label>
              <input
                id="pp-cats"
                value={categories}
                onChange={(e) => setCategories(e.target.value)}
                className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-4 flex items-center gap-2 border-t border-aegis-border-subtle pt-3">
            <input
              id="pp-allow-unknown"
              type="checkbox"
              checked={allowUnknownMerchants}
              onChange={(e) => setAllowUnknownMerchants(e.target.checked)}
              className="h-3.5 w-3.5 border border-aegis-border bg-aegis-card text-aegis-accent focus:ring-0"
            />
            <label htmlFor="pp-allow-unknown" className="font-mono text-xs text-aegis-text-muted">
              Allow Unknown Merchants (bypass vendor allowlist checking)
            </label>
          </div>

          {merchants.length > 0 && (
            <fieldset className="mt-4 border border-aegis-border-subtle p-3 bg-aegis-card">
              <legend className="font-mono text-[10px] uppercase text-aegis-text-faint px-1">Allowlisted Vendors</legend>
              <div className="flex flex-wrap gap-2">
                {merchants.map((m) => {
                  const checked = selectedMerchantIds.includes(m.id);
                  return (
                    <label
                      key={m.id}
                      className={`inline-flex items-center gap-2 border px-2.5 py-1 font-mono text-xs cursor-pointer transition-colors ${
                        checked
                          ? "border-aegis-accent bg-aegis-secondary text-aegis-accent"
                          : "border-aegis-border bg-aegis-surface text-aegis-text-muted"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setSelectedMerchantIds((prev) =>
                            checked ? prev.filter((id) => id !== m.id) : [...prev, m.id],
                          )
                        }
                        className="sr-only"
                      />
                      <span>{m.name}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}

          <div className="mt-5 flex justify-end">
            <button
              type="submit"
              disabled={!agentId}
              className="border border-aegis-accent bg-aegis-accent px-5 py-2 font-mono text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50 transition-colors shadow-editorial"
            >
              Issue Spending Passport
            </button>
          </div>
        </form>
      )}

      {/* Passports List */}
      <section className="border border-aegis-border bg-aegis-surface p-5 rounded-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-text-faint">
              ACTIVE ENFORCEMENT
            </span>
            <h2 className="text-sm font-semibold text-aegis-text-primary">
              Spending Passports ({filteredPassports.length})
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setOffset(0);
              }}
              placeholder="Filter by agent, UUID, status..."
              className="w-64 border border-aegis-border bg-aegis-card px-3 py-1.5 font-mono text-xs text-aegis-text-primary placeholder:text-aegis-text-faint focus:border-aegis-accent focus:outline-none"
            />
            <div className="flex items-center gap-1.5 font-mono text-xs text-aegis-text-muted">
              <span>LIMIT:</span>
              <select
                id="pp-limit-select"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
                className="border border-aegis-border bg-aegis-card px-2 py-1 text-xs text-aegis-text-primary focus:outline-none"
              >
                <option value={6}>6</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {pagedPassports.length === 0 ? (
            <div className="col-span-full border border-dashed border-aegis-border bg-aegis-card p-8 text-center font-mono text-xs text-aegis-text-muted">
              {searchQuery ? "No passports matching filter query." : "No passports registered."}
            </div>
          ) : (
            pagedPassports.map((p) => {
              const avail = Math.max(0, p.total_budget_minor - p.spent_minor - p.reserved_minor);
              const usedPct =
                p.total_budget_minor > 0
                  ? Math.min(100, Math.round(((p.spent_minor + p.reserved_minor) / p.total_budget_minor) * 100))
                  : 0;
              return (
                <article key={p.id} className="border border-aegis-border bg-aegis-card p-5 flex flex-col justify-between rounded-sm">
                  <div>
                    <div className="flex items-start justify-between border-b border-aegis-border-subtle pb-3">
                      <div>
                        <div className="font-sans text-sm font-semibold text-aegis-text-primary">
                          {agentNameById.get(p.agent_id) ?? p.agent_id}
                        </div>
                        <div className="font-mono text-[10px] text-aegis-text-faint mt-0.5">
                          ID: {p.id}
                        </div>
                      </div>
                      <StatusBadge label={p.status} />
                    </div>

                    <div className="mt-4 font-mono">
                      <div className="flex justify-between text-xs text-aegis-text-muted">
                        <span>AVAILABLE: <span className="text-aegis-accent font-semibold">{formatMinorCurrency(avail, p.currency)}</span></span>
                        <span>TOTAL: <span className="text-aegis-text-primary">{formatMinorCurrency(p.total_budget_minor, p.currency)}</span></span>
                      </div>
                      <div className="mt-2 h-1.5 w-full bg-aegis-surface border border-aegis-border">
                        <div className="h-full bg-aegis-accent transition-all duration-300" style={{ width: `${usedPct}%` }} />
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-aegis-border-subtle pt-2.5 text-[10px] text-aegis-text-faint">
                        <div>PER TX: <span className="text-aegis-text-muted">{formatMinorCurrency(p.per_tx_limit_minor, p.currency)}</span></div>
                        <div>DAILY: <span className="text-aegis-text-muted">{formatMinorCurrency(p.daily_limit_minor, p.currency)}</span></div>
                        <div>ESCALATE ≥ <span className="text-aegis-copper">{formatMinorCurrency(p.human_approval_threshold_minor, p.currency)}</span></div>
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[10px]">
                      <span className={`border px-1.5 py-0.5 uppercase ${
                        p.allow_unknown_merchants
                          ? "border-[#4A3728] bg-[#211812] text-aegis-copper"
                          : "border-aegis-border bg-aegis-surface text-aegis-text-muted"
                      }`}>
                        {p.allow_unknown_merchants ? "Unknown Vendors: ALLOWED" : "STRICT ALLOWLIST"}
                      </span>
                      {p.allowed_categories && p.allowed_categories.length > 0 && (
                        <span className="border border-aegis-border bg-aegis-surface px-1.5 py-0.5 text-aegis-text-muted">
                          CATS: {p.allowed_categories.join(", ")}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-aegis-border pt-3 font-mono text-[10px] text-aegis-text-faint">
                    <span>EXPIRES: {formatIsoDateTime(p.expires_at)}</span>
                    <div className="flex items-center gap-2">
                      {hasPermission("passports:write") && p.status === "ACTIVE" && (
                        <>
                          <button
                            type="button"
                            onClick={() => openEditPolicyModal(p)}
                            className="border border-aegis-border bg-aegis-surface px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary transition-colors"
                          >
                            EDIT
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmRevoke(p)}
                            className="border border-[#4A2828] bg-[#211212] px-2.5 py-1 text-[#EF5350] hover:bg-[#ff6b6b]/20 transition-colors"
                          >
                            REVOKE
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </article>
              );
            })
          )}
        </div>

        {/* Pagination Bar */}
        {filteredPassports.length > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 font-mono text-xs text-aegis-text-faint">
            <div>
              SHOWING {Math.min(filteredPassports.length, offset + 1)}–{Math.min(filteredPassports.length, offset + limit)} OF {filteredPassports.length} PASSPORTS
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                PREV
              </button>
              <span>
                PAGE {Math.floor(offset / limit) + 1} OF {Math.max(1, Math.ceil(filteredPassports.length / limit))}
              </span>
              <button
                type="button"
                disabled={offset + limit >= filteredPassports.length}
                onClick={() => setOffset((prev) => prev + limit)}
                className="border border-aegis-border bg-aegis-card px-2.5 py-1 text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary disabled:opacity-40"
              >
                NEXT
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Inline PATCH Policy Limit Editor Modal */}
      {editingPassport && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <form
            onSubmit={(e) => void handleSavePolicy(e)}
            className="w-full max-w-lg border border-aegis-border bg-aegis-surface p-6 shadow-panel space-y-4 rounded-sm"
          >
            <div className="flex items-start justify-between border-b border-aegis-border pb-3">
              <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
                  GUARDRAIL MUTATION
                </span>
                <h3 className="text-sm font-semibold text-aegis-text-primary mt-0.5">Edit Policy Limits</h3>
                <p className="font-mono text-[10px] text-aegis-text-faint">
                  PASSPORT: {truncateId(editingPassport.id)} • AGENT: {agentNameById.get(editingPassport.agent_id) ?? editingPassport.agent_id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingPassport(null)}
                className="text-aegis-text-muted hover:text-aegis-text-primary font-mono text-sm"
              >
                ✕
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 font-mono">
              <div>
                <label htmlFor="edit-pertx" className="block text-xs uppercase text-aegis-text-muted">
                  Per-Transaction Limit (USD)
                </label>
                <input
                  id="edit-pertx"
                  type="number"
                  step="0.01"
                  min="0"
                  required
                  value={editPerTxDollars}
                  onChange={(e) => setEditPerTxDollars(e.target.value)}
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="edit-daily" className="block text-xs uppercase text-aegis-text-muted">
                  Daily Limit (USD)
                </label>
                <input
                  id="edit-daily"
                  type="number"
                  step="0.01"
                  min="0"
                  required
                  value={editDailyDollars}
                  onChange={(e) => setEditDailyDollars(e.target.value)}
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="sm:col-span-2">
                <label htmlFor="edit-threshold" className="block text-xs uppercase text-aegis-text-muted">
                  Human Approval Threshold (USD)
                </label>
                <input
                  id="edit-threshold"
                  type="number"
                  step="0.01"
                  min="0"
                  required
                  value={editThresholdDollars}
                  onChange={(e) => setEditThresholdDollars(e.target.value)}
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="sm:col-span-2">
                <label htmlFor="edit-cats" className="block text-xs uppercase text-aegis-text-muted">
                  Allowed Categories (CSV)
                </label>
                <input
                  id="edit-cats"
                  type="text"
                  value={editCategories}
                  onChange={(e) => setEditCategories(e.target.value)}
                  className="mt-1.5 w-full border border-aegis-border bg-aegis-card px-3 py-2 text-xs text-aegis-text-primary focus:border-aegis-accent focus:outline-none"
                />
              </div>

              <div className="sm:col-span-2">
                <label className="inline-flex items-center gap-2 text-xs font-mono text-aegis-text-muted">
                  <input
                    type="checkbox"
                    checked={editAllowUnknown}
                    onChange={(e) => setEditAllowUnknown(e.target.checked)}
                    className="h-3.5 w-3.5 border border-aegis-border bg-aegis-card text-aegis-accent focus:ring-0"
                  />
                  <span>Allow Unknown Vendors (bypass allowlist verification)</span>
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-aegis-border font-mono">
              <button
                type="button"
                onClick={() => setEditingPassport(null)}
                className="border border-aegis-border bg-aegis-card px-3.5 py-1.5 text-xs text-aegis-text-muted hover:border-aegis-border-active hover:text-aegis-text-primary"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingPolicy}
                className="border border-aegis-accent bg-aegis-accent px-4 py-1.5 text-xs font-bold uppercase tracking-wider text-aegis-bg hover:bg-aegis-accent-hover disabled:opacity-50"
              >
                {savingPolicy ? "Saving…" : "Save Policy"}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(confirmRevoke)}
        title="Revoke Spending Passport"
        description="Revoking this passport permanently blocks any future authorizations bound to it."
        confirmLabel="Revoke Passport"
        destructive
        onCancel={() => setConfirmRevoke(null)}
        onConfirm={() => {
          if (confirmRevoke) void handleRevoke(confirmRevoke);
        }}
      />
    </AppShell>
  );
}
