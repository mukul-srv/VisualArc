"use client";

import { useEffect, useRef, type ReactNode } from "react";
import type { DraftResult } from "../lib/jobs";
import type { FixAction } from "../lib/issues";
import { IssueList } from "./IssueList";
import { PlanOverlay } from "./PlanOverlay";

const m2 = (mm2: number) => (mm2 / 1e6).toFixed(1);

/** Guided review before saving: per floor the plan drawn from the draft, stats and issues with fix
 *  actions. Accept is disabled while blocking issues remain. Nothing here is stored. */
export function ReviewPanel(p: { draft: DraftResult; stale?: boolean; busy: boolean; progress?: ReactNode; onClose: () => void; onFix: (a: FixAction) => void; onRerun: () => void; onAccept: () => void }) {
  const { draft } = p;
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // onClose ignores the close event of an effect re-run (React strict mode reopens the dialog before it fires)
  useEffect(() => {
    const d = dialog.current;
    d?.showModal();
    heading.current?.focus();
    return () => {
      d?.close();
      document.getElementById("check-plan")?.focus(); // the page button that opened this (it was disabled while checking, so activeElement is not reliable)
    };
  }, []);
  return (
    <dialog ref={dialog} aria-labelledby="review-heading" onCancel={(e) => p.busy && e.preventDefault()} onClose={() => !dialog.current?.open && p.onClose()}>
    <section aria-label="Review">
      <h2 id="review-heading" tabIndex={-1} ref={heading}>Review before saving</h2>
      {draft.floors.map((f, n) => (
        <div key={f.key ?? n}>
          {f.name && <h3>{f.name}</h3>}
          {f.stats && (
            <p>
              {f.stats.walls} walls,{" "}
              {f.stats.openings > 0 ? `${f.stats.openings} doors and windows` : "No doors or windows found"},{" "}
              {f.stats.rooms > 0 ? `${f.stats.rooms} rooms, ${m2(f.stats.area)} m² total room area` : "No rooms found yet"}
            </p>
          )}
          {f.overlay ? <PlanOverlay overlay={f.overlay} /> : <p>No plan to show for this floor.</p>}
          <IssueList issues={f.issues} onFix={p.onFix} />
        </div>
      ))}
      {p.progress}
      <button type="button" disabled={p.busy} onClick={() => dialog.current?.close()}>Back to settings</button>{" "}
      <button disabled={p.busy} onClick={p.onRerun}>Check again</button>{" "}
      <button disabled={p.busy || draft.blocking || p.stale} onClick={p.onAccept}>Create 3D model</button>
      {p.stale && <p role="status">Press Check again: settings changed.</p>}
      {draft.blocking && <p role="status">Resolve the blocking issues, then check again.</p>}
    </section>
    </dialog>
  );
}
