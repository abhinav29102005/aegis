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
      className="w-full max-w-md rounded-xl border border-aegis-border bg-aegis-panel p-6 text-slate-100 shadow-2xl"
    >
      <h2 id={titleId} className="text-lg font-semibold text-white">
        {title}
      </h2>
      <p className="mt-2 text-sm text-slate-300">{description}</p>
      <div className="mt-6 flex justify-end gap-3">
        <button
          type="button"
          autoFocus={destructive}
          disabled={busy}
          onClick={onCancel}
          className="rounded-lg border border-aegis-border bg-aegis-surface px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          autoFocus={!destructive}
          disabled={busy}
          onClick={onConfirm}
          className={
            destructive
              ? "rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
              : "rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
          }
        >
          {busy ? "Processing…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
