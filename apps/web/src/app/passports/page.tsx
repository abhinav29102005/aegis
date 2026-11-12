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

  // FIX: Fixed useCallback dependency re-fetch loop by removing agentId and selectedMerchantIds.length
  // from dependencies and using functional state updaters.
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
      setAgentId((prev) => prev || a[0]?.id || "");
      setSelectedMerchantIds((prev) => (prev.length === 0 && m.length > 0 ? [m[0].id] : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load passports");
    }
  }, [limit, offset, searchQuery, session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const agentNameById = useMemo(() => new Map(agents.map((a) => [a.id, a.name])), [agents]);

  // Client-side search filtering and pagination
  const filteredPassports = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return passports;
    return passports.filter((p) => {
      const agentName = (agentNameById.get(p.agent_id) ?? "").toLowerCase();
      return (
        p.id.toLowerCase().includes(q) ||
        p.agent_id.toLowerCase().includes(q) ||
        agentName.includes(q) ||
        p.currency.toLowerCase().includes(q) ||
        p.status.toLowerCase().includes(q) ||
        p.allowed_categories.some((c) => c.toLowerCase().includes(q))
      );
    });
  }, [passports, searchQuery, agentNameById]);

  const pagedPassports = useMemo(() => {
    return filteredPassports.slice(offset, offset + limit);
  }, [filteredPassports, offset, limit]);

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
      // Inline PATCH policy limit editor modal (PATCH /v1/guardian/passports/{id}/policy with fallback to /passports/{id})
      try {
        await apiRequest(`/v1/guardian/passports/${editingPassport.id}/policy`, {
          method: "PATCH",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: patchBody,
        });
      } catch {
        // Fallback to /passports/{id} if /policy route is not exposed directly
        await apiRequest(`/v1/guardian/passports/${editingPassport.id}`, {
          method: "PATCH",
          token: session.access_token,
          orgId: session.active_tenant_id,
          body: patchBody,
        });
      }
      setNotice(`Updated policy guardrails for passport ${truncateId(editingPassport.id)}.`);
      setEditingPassport(null);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update passport policy");
    } finally {
      setSavingPolicy(false);
    }
  }

  async function handleRevoke(p: PassportRecord) {
    if (!session) return;
    try {
      await apiRequest(`/v1/guardian/passports/${p.id}/revoke`, {
        method: "POST",
        token: session.access_token,
        orgId: session.active_tenant_id,
      });
      setConfirmRevoke(null);
      setNotice(`Passport ${truncateId(p.id)} revoked.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke passport");
    }
  }

  return (
    <AppShell title="Spending Passports & Budgets" subtitle="Issue deterministic policy guardrails, spend caps, and approval thresholds">
      {error && (
        <div role="status" className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mb-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          {notice}
        </div>
      )}

      {hasPermission("passports:write") && (
        <form onSubmit={(e) => void handleCreatePassport(e)} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
          <h2 className="text-base font-semibold text-white">Issue New Spending Passport</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label htmlFor="pp-agent" className="block text-xs font-medium text-slate-300">
                Target Agent *
              </label>
              <select
                id="pp-agent"
                required
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.status})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="pp-total" className="block text-xs font-medium text-slate-300">
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
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="pp-pertx" className="block text-xs font-medium text-slate-300">
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
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="pp-daily" className="block text-xs font-medium text-slate-300">
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
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="pp-thresh" className="block text-xs font-medium text-slate-300">
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
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label htmlFor="pp-cats" className="block text-xs font-medium text-slate-300">
                Allowed Categories (comma-separated)
              </label>
              <input
                id="pp-cats"
                value={categories}
                onChange={(e) => setCategories(e.target.value)}
                className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
              />
            </div>
          </div>

          {/* allow_unknown_merchants toggle */}
          <div className="mt-4 flex items-center gap-2">
            <input
              id="pp-allow-unknown"
              type="checkbox"
              checked={allowUnknownMerchants}
              onChange={(e) => setAllowUnknownMerchants(e.target.checked)}
              className="h-4 w-4 rounded border-aegis-border bg-aegis-bg text-sky-500 focus:ring-sky-400"
            />
            <label htmlFor="pp-allow-unknown" className="text-xs font-medium text-slate-200">
              Allow Unknown Merchants (bypass allowlist check for unlisted vendors)
            </label>
          </div>

          {merchants.length > 0 && (
            <fieldset className="mt-4">
              <legend className="text-xs font-medium text-slate-300">Allowed Merchants</legend>
              <div className="mt-2 flex flex-wrap gap-3">
                {merchants.map((m) => {
                  const checked = selectedMerchantIds.includes(m.id);
                  return (
                    <label key={m.id} className="inline-flex items-center gap-2 rounded-lg border border-aegis-border bg-aegis-bg px-3 py-1.5 text-xs text-slate-200">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setSelectedMerchantIds((prev) =>
                            checked ? prev.filter((id) => id !== m.id) : [...prev, m.id],
                          )
                        }
                      />
                      <span>{m.name}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}

          <button
            type="submit"
            disabled={!agentId}
            className="mt-4 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
          >
            Issue Spending Passport
          </button>
        </form>
      )}

      {/* Passports Header with Search & Pagination */}
      <section className="mt-8 rounded-xl border border-aegis-border bg-aegis-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-aegis-border pb-4">
          <h2 className="text-base font-semibold text-white">
            Spending Passports ({filteredPassports.length})
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setOffset(0);
                }}
                placeholder="Search passports (agent, ID, status)..."
                className="w-64 rounded-lg border border-aegis-border bg-aegis-bg px-3 py-1.5 text-xs text-white placeholder-slate-400"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery("");
                    setOffset(0);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-300">
              <label htmlFor="pp-limit-select">Limit:</label>
              <select
                id="pp-limit-select"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
                className="rounded border border-aegis-border bg-aegis-bg px-2 py-1 text-xs text-white"
              >
                <option value={6}>6</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {pagedPassports.length === 0 ? (
            <div className="col-span-full rounded-xl border border-dashed border-aegis-border bg-aegis-panel p-8 text-center text-sm text-slate-400">
              {searchQuery ? "No spending passports matching your search." : "No spending passports issued yet."}
            </div>
          ) : (
            pagedPassports.map((p) => {
              const avail = Math.max(0, p.total_budget_minor - p.spent_minor - p.reserved_minor);
              const usedPct =
                p.total_budget_minor > 0
                  ? Math.min(100, Math.round(((p.spent_minor + p.reserved_minor) / p.total_budget_minor) * 100))
                  : 0;
              return (
                <article key={p.id} className="rounded-xl border border-aegis-border bg-aegis-panel p-5 flex flex-col justify-between">
                  <div>
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-sm font-semibold text-white">
                          {agentNameById.get(p.agent_id) ?? p.agent_id}
                        </div>
                        <div className="font-mono text-xs text-slate-400">{p.id}</div>
                      </div>
                      <StatusBadge label={p.status} />
                    </div>

                    <div className="mt-4">
                      <div className="flex justify-between text-xs text-slate-300">
                        <span>Available: {formatMinorCurrency(avail, p.currency)}</span>
                        <span>Total: {formatMinorCurrency(p.total_budget_minor, p.currency)}</span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-800">
                        <div className="h-full bg-sky-400" style={{ width: `${usedPct}%` }} />
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-400">
                        <div>Per Tx: {formatMinorCurrency(p.per_tx_limit_minor, p.currency)}</div>
                        <div>Daily: {formatMinorCurrency(p.daily_limit_minor, p.currency)}</div>
                        <div>Approval ≥ {formatMinorCurrency(p.human_approval_threshold_minor, p.currency)}</div>
                      </div>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
                      <span className={`inline-flex items-center rounded px-2 py-0.5 font-medium ${
                        p.allow_unknown_merchants
                          ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                          : "bg-slate-800 text-slate-300"
                      }`}>
                        {p.allow_unknown_merchants ? "Unknown Merchants: Allowed" : "Strict Allowlist Only"}
                      </span>
                      {p.allowed_categories && p.allowed_categories.length > 0 && (
                        <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">
                          Categories: {p.allowed_categories.join(", ")}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-aegis-border pt-3 text-xs text-slate-400">
                    <span>Expires {formatIsoDateTime(p.expires_at)}</span>
                    <div className="flex items-center gap-2">
                      {hasPermission("passports:write") && p.status === "ACTIVE" && (
                        <>
                          <button
                            type="button"
                            onClick={() => openEditPolicyModal(p)}
                            className="rounded border border-sky-500/40 px-2.5 py-1 text-xs text-sky-300 hover:bg-sky-500/15"
                          >
                            Edit Policy
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmRevoke(p)}
                            className="rounded border border-rose-500/40 px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-500/15"
                          >
                            Revoke
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
          <div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-aegis-border pt-3 text-xs text-slate-400">
            <div>
              Showing {Math.min(filteredPassports.length, offset + 1)} to {Math.min(filteredPassports.length, offset + limit)} of {filteredPassports.length} passports
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Previous
              </button>
              <span>
                Page {Math.floor(offset / limit) + 1} of {Math.max(1, Math.ceil(filteredPassports.length / limit))}
              </span>
              <button
                type="button"
                disabled={offset + limit >= filteredPassports.length}
                onClick={() => setOffset((prev) => prev + limit)}
                className="rounded border border-aegis-border bg-aegis-bg px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Inline PATCH Policy Limit Editor Modal */}
      {editingPassport && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form
            onSubmit={(e) => void handleSavePolicy(e)}
            className="w-full max-w-lg rounded-xl border border-aegis-border bg-aegis-surface p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-base font-semibold text-white">Edit Policy Limits & Guardrails</h3>
                <p className="text-xs text-slate-400">
                  Passport {truncateId(editingPassport.id)} · Agent {agentNameById.get(editingPassport.agent_id) ?? editingPassport.agent_id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingPassport(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="edit-pertx" className="block text-xs font-medium text-slate-300">
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
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>

              <div>
                <label htmlFor="edit-daily" className="block text-xs font-medium text-slate-300">
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
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>

              <div className="sm:col-span-2">
                <label htmlFor="edit-threshold" className="block text-xs font-medium text-slate-300">
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
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>

              <div className="sm:col-span-2">
                <label htmlFor="edit-cats" className="block text-xs font-medium text-slate-300">
                  Allowed Categories (comma-separated)
                </label>
                <input
                  id="edit-cats"
                  type="text"
                  value={editCategories}
                  onChange={(e) => setEditCategories(e.target.value)}
                  placeholder="SOFTWARE, COMPUTE, API"
                  className="mt-1 w-full rounded-lg border border-aegis-border bg-aegis-bg px-3 py-2 text-sm text-white"
                />
              </div>

              <div className="sm:col-span-2">
                <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-200">
                  <input
                    type="checkbox"
                    checked={editAllowUnknown}
                    onChange={(e) => setEditAllowUnknown(e.target.checked)}
                    className="h-4 w-4 rounded border-aegis-border bg-aegis-bg text-sky-500 focus:ring-sky-400"
                  />
                  <span>Allow Unknown Merchants (bypass allowlist verification)</span>
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-4 border-t border-aegis-border">
              <button
                type="button"
                onClick={() => setEditingPassport(null)}
                className="rounded-lg border border-aegis-border px-3.5 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={savingPolicy}
                className="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
              >
                {savingPolicy ? "Saving Policy…" : "Save Policy"}
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
