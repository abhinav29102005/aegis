export function formatMinorCurrency(amountMinor: number, currency = "USD"): string {
  const major = amountMinor / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.toUpperCase(),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(major);
  } catch {
    return `${currency.toUpperCase()} ${major.toFixed(2)}`;
  }
}

export function formatIsoDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

export function truncateId(id: string | null | undefined, visible = 8): string {
  if (!id) return "—";
  return id.length <= visible ? id : `${id.slice(0, visible)}…`;
}

export function badgeToneForStatus(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  const upper = status.toUpperCase();
  if (
    ["SUCCEEDED", "ACTIVE", "ALLOW", "APPROVED", "CONSISTENT", "DELIVERED", "PUBLISHED", "RESOLVED", "VERIFIED"].includes(upper)
  ) {
    return "success";
  }
  if (
    [
      "ESCALATE",
      "AWAITING_APPROVAL",
      "AWAITING_PAYPAL_BUYER",
      "PENDING",
      "PENDING_PROVIDER",
      "CHECKOUT_READY",
      "UNDER_INVESTIGATION",
      "DRAFT_READY",
      "APPROVED_FOR_SUBMISSION",
      "OPEN",
    ].includes(upper)
  ) {
    return "warning";
  }
  if (
    ["DENY", "FAILED", "REVOKED", "EXPIRED", "REJECTED", "DEAD_LETTER", "INTEGRITY_FAILURE", "DRIFT_DETECTED", "SUSPENDED"].includes(
      upper,
    )
  ) {
    return "danger";
  }
  if (["SUBMITTED", "SYNTHETIC_DEMO"].includes(upper)) {
    return "info";
  }
  return "neutral";
}
