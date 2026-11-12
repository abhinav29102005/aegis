import React from "react";
import { badgeToneForStatus } from "@/lib/format";

const TONE_CLASSES = {
  success: "border-[#3A4A28] bg-[#162112] text-[#D7F17B]",
  warning: "border-[#4A3728] bg-[#211812] text-[#D58A62]",
  danger: "border-[#4A2828] bg-[#211212] text-[#EF5350]",
  info: "border-[#28332B] bg-[#1B211D] text-[#A8B1A9]",
  neutral: "border-[#28332B] bg-[#161C18] text-[#8C988E]",
};

const DOT_CLASSES = {
  success: "bg-[#D7F17B]",
  warning: "bg-[#D58A62]",
  danger: "bg-[#EF5350]",
  info: "bg-[#A8B1A9]",
  neutral: "bg-[#657167]",
};

export function StatusBadge({ label }: { label: string }) {
  const tone = badgeToneForStatus(label);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wider ${TONE_CLASSES[tone]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOT_CLASSES[tone]}`} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
