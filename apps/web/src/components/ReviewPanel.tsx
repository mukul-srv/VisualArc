"use client";

import type { DraftResult } from "../lib/jobs";
import type { FixAction } from "../lib/issues";
import { IssueList } from "./IssueList";
import { PlanOverlay } from "./PlanOverlay";

const m2 = (mm2: number) => (mm2 / 1e6).toFixed(1);

/** Guided review before saving: per floor the plan drawn from the draft, stats and issues with fix
 *  actions. Accept is disabled while blocking issues remain. Nothing here is stored. */
export function ReviewPanel(p: { draft: DraftResult; busy: boolean; onFix: (a: FixAction) => void; onRerun: () => void; onAccept: () => void }) {
  const { draft } = p;
  return (
    <section aria-label="Review">
      <h2>Review before saving</h2>
      {draft.floors.map((f, n) => (
        <div key={f.key ?? n}>
          {f.name && <h3>{f.name}</h3>}
          {f.stats && (
            <p>
              {f.stats.walls} walls, {f.stats.openings} openings, {f.stats.rooms} rooms, {m2(f.stats.area)} m² total room area
            </p>
          )}
          {f.overlay ? <PlanOverlay overlay={f.overlay} /> : <p>No plan to show for this floor.</p>}
          <IssueList issues={f.issues} onFix={p.onFix} />
        </div>
      ))}
      <button disabled={p.busy} onClick={p.onRerun}>Re-run review</button>{" "}
      <button disabled={p.busy || draft.blocking} onClick={p.onAccept}>Accept &amp; generate</button>
      {draft.blocking && <p role="status">Resolve the blocking issues, then re-run the review.</p>}
    </section>
  );
}
