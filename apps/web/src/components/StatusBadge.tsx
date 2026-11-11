import React from "react";
import { badgeToneForStatus } from "@/lib/format";

const TONE_CLASSES = {
  success: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
  warning: "border-amber-500/30 bg-amber-500/15 text-amber-300",
  danger: "border-rose-500/30 bg-rose-500/15 text-rose-300",
  info: "border-sky-500/30 bg-sky-500/15 text-sky-300",
  neutral: "border-slate-600/40 bg-slate-700/30 text-slate-300",
};

export function StatusBadge({ label }: { label: string }) {
  const tone = badgeToneForStatus(label);
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}>
      {label}
    </span>
  );
}
