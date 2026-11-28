"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** A destructive confirmation as a native modal <dialog>: focus is trapped, Esc cancels, Cancel has focus
 *  first, and focus returns to what opened it. Mount it only while the question is open. */
export function ConfirmDialog(p: { label: string; confirmLabel: string; busy?: boolean; onConfirm: () => void; onCancel: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const d = ref.current;
    const opener = document.activeElement as HTMLElement | null;
    d?.showModal();
    cancel.current?.focus();
    return () => {
      d?.close();
      opener?.focus?.();
    };
  }, []);
  return (
    <dialog ref={ref} role="alertdialog" aria-label={p.label} onClose={() => !ref.current?.open && p.onCancel()}>
      <p>{p.children}</p>
      <button type="button" ref={cancel} onClick={p.onCancel}>Cancel</button>{" "}
      <button type="button" disabled={p.busy} onClick={p.onConfirm}>{p.confirmLabel}</button>
    </dialog>
  );
}
