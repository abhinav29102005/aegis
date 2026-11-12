"use client";

import React, { useEffect, useId, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive = false,
  busy = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onClose={() => {
        if (dialogRef.current) dialogRef.current.returnValue = "";
        onCancel();
      }}
      onCancel={(e) => {
        if (busy) {
          e.preventDefault();
        }
      }}
      className="w-full max-w-md rounded-md border border-aegis-border bg-aegis-surface p-6 text-aegis-text-primary shadow-panel"
    >
      <div className="flex items-center gap-2 border-b border-aegis-border pb-3">
        <span className="font-mono text-[10px] uppercase tracking-widest text-aegis-accent font-semibold">
          CONTROL CONFIRMATION
        </span>
      </div>
      <h2 id={titleId} className="mt-3 text-base font-semibold text-aegis-text-primary tracking-tight">
        {title}
      </h2>
      <p className="mt-2 text-xs leading-relaxed text-aegis-text-muted">{description}</p>
      <div className="mt-6 flex justify-end gap-3 pt-3 border-t border-aegis-border-subtle">
        <button
          type="button"
          autoFocus={destructive}
          disabled={busy}
          onClick={onCancel}
          className="rounded-[3px] border border-aegis-border bg-aegis-card px-4 py-2 font-mono text-xs uppercase tracking-wider text-aegis-text-primary hover:bg-aegis-secondary hover:border-aegis-border-active disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          autoFocus={!destructive}
          disabled={busy}
          onClick={onConfirm}
          className={`rounded-[3px] px-4 py-2 font-mono text-xs uppercase tracking-wider font-semibold disabled:opacity-50 transition-colors ${
            destructive
              ? "bg-[#EF5350] text-[#111513] hover:bg-[#ff6b6b]"
              : "bg-aegis-accent text-[#111513] hover:bg-aegis-accent-hover"
          }`}
        >
          {busy ? "Processing…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
