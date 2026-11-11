"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, type AgentRecord, type MerchantRecord, type PassportRecord } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatIsoDateTime, formatMinorCurrency } from "@/lib/format";

export default function PassportsPage() {
  const { session, hasPermission } = useAuth();
  const [passports, setPassports] = useState<PassportRecord[]>([]);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [merchants, setMerchants] = useState<MerchantRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<PassportRecord | null>(null);

  const [agentId, setAgentId] = useState("");
  const [totalDollars, setTotalDollars] = useState("100.00");
  const [perTxDollars, setPerTxDollars] = useState("50.00");
  const [dailyDollars, setDailyDollars] = useState("100.00");
  const [thresholdDollars, setThresholdDollars] = useState("30.00");
  const [selectedMerchantIds, setSelectedMerchantIds] = useState<string[]>([]);
  const [categories, setCategories] = useState("SOFTWARE");

  const loadData = useCallback(async () => {
    if (!session) return;
    try {
      const [p, a, m] = await Promise.all([
        apiRequest<PassportRecord[]>("/v1/guardian/passports", {
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
      if (!agentId && a.length > 0) setAgentId(a[0].id);
      if (selectedMerchantIds.length === 0 && m.length > 0) setSelectedMerchantIds([m[0].id]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load passports");
    }
  }, [agentId, selectedMerchantIds.length, session]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleCreatePassport(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError(null);
    const toMinor = (val: string) => Math.max(0, Math.round(Number.parseFloat(val || "0") * 100));
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
          allow_unknown_merchants: false,
          expires_in_days: 30,
        },
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to issue spending passport");
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
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke passport");
    }
  }

  const agentNameById = new Map(agents.map((a) => [a.id, a.name]));

  return (
    <AppShell title="Spending Passports & Budgets" subtitle="Issue deterministic policy guardrails, spend caps, and approval thresholds">
      {error && (
        <div role="status" className="mb-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
          {error}
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

      <section className="mt-8 grid gap-4 md:grid-cols-2">
        {passports.length === 0 ? (
          <div className="col-span-full rounded-xl border border-dashed border-aegis-border bg-aegis-surface p-8 text-center text-sm text-slate-400">
            No spending passports issued yet.
          </div>
        ) : (
          passports.map((p) => {
            const avail = Math.max(0, p.total_budget_minor - p.spent_minor - p.reserved_minor);
            const usedPct = p.total_budget_minor > 0 ? Math.min(100, Math.round(((p.spent_minor + p.reserved_minor) / p.total_budget_minor) * 100)) : 0;
            return (
              <article key={p.id} className="rounded-xl border border-aegis-border bg-aegis-surface p-5">
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

                <div className="mt-4 flex items-center justify-between border-t border-aegis-border pt-3 text-xs text-slate-400">
                  <span>Expires {formatIsoDateTime(p.expires_at)}</span>
                  {hasPermission("passports:write") && p.status === "ACTIVE" && (
                    <button
                      type="button"
                      onClick={() => setConfirmRevoke(p)}
                      className="rounded border border-rose-500/40 px-2.5 py-1 text-xs text-rose-300 hover:bg-rose-500/15"
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </article>
            );
          })
        )}
      </section>

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
