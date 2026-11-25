"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { arrowStep, canPlace, clickToPlan, moveLight, nudgeLight, commitCoord, placeLight, planToScreen, squareBounds, squareFit } from "../lib/light-plan";
import { getPlanOverlay, overlayBounds, wallCorners, type OverlayData } from "../lib/overlay";
import { MAX_LIGHTS, type ArtificialLight } from "../lib/site-lighting";

const S = 300; // the square, px

/** A number box that keeps what is typed as text ("", "-" are fine while typing) and commits, clamped, on blur or
 *  Enter. The parent re-keys it when the light's value changes (drag, nudge), which resets the text. */
function CoordInput({ label, value, disabled, onCommit }: { label: string; value: number; disabled: boolean; onCommit: (text: string) => void }) {
  const [draft, setDraft] = useState(String(value));
  return (
    <input
      aria-label={label}
      type="text"
      inputMode="numeric"
      style={{ width: 80 }}
      disabled={disabled}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        onCommit(draft);
        setDraft(String(value)); // blank or junk: show the current value again (a valid commit re-keys this input)
      }}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

type Props = {
  projectId: string | null; // null: not a project, no plan to draw
  floors: { id: string; name: string }[]; // lowest first
  share?: string | null;
  lights: ArtificialLight[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChange: (lights: ArtificialLight[]) => void;
  canEdit: boolean;
};

/** Square 2D plan of one floor for placing lights: "Add light source" puts a new dot at the centre of the plan
 *  (selected), drag a marker to move it, click a marker to select it, arrow keys nudge the selected one (shift: 500 mm), Delete removes it.
 *  Viewers see the markers only. The plan is the floor's own data (the plan overlay), drawn faintly. */
export function LightPlan({ projectId, floors, share, lights, selectedId, onSelect, onChange, canEdit }: Props) {
  const [tab, setTab] = useState<string | null>(null);
  const sel = lights.find((l) => l.id === selectedId) ?? null;
  const floorId = sel?.floor_id ?? tab ?? floors[0]?.id ?? null;
  const [loaded, setLoaded] = useState<{ key: string; data: OverlayData | null; error: string | null } | null>(null);
  const drag = useRef<string | null>(null);
  const key = projectId && floorId ? `${projectId}/${floorId}/${share ?? ""}` : null;

  useEffect(() => {
    if (!key || !projectId || !floorId) return;
    let live = true;
    getPlanOverlay(projectId, floorId, fetch, share).then((r) => live && setLoaded({ key, data: r.ok ? r.overlay : null, error: r.ok ? null : r.message }));
    return () => {
      live = false;
    };
  }, [key, projectId, floorId, share]);

  const data = loaded?.key === key ? loaded.data : null;
  const sq = useMemo(() => squareBounds(data ? overlayBounds(data) : null), [data]);
  const f = useMemo(() => squareFit(sq, S), [sq]);
  const pt = (x: number, y: number) => planToScreen(f, x, y).map((v) => v.toFixed(1)).join(",");
  const mine = lights.filter((l) => l.floor_id === floorId);
  const at = (e: { clientX: number; clientY: number; currentTarget: Element }) => {
    const svg = e.currentTarget.closest("svg")!;
    const r = svg.getBoundingClientRect();
    return clickToPlan(f, ((e.clientX - r.left) * S) / r.width, ((e.clientY - r.top) * S) / r.height);
  };

  if (!projectId || !floorId) return <div>The plan is available for saved projects.</div>;
  return (
    <div>
      <div role="group" aria-label="Floor of the plan">
        {floors.map((fl) => (
          <button
            key={fl.id}
            aria-pressed={fl.id === floorId}
            onClick={() => {
              setTab(fl.id);
              if (sel && sel.floor_id !== fl.id) onSelect(null);
            }}
          >
            {fl.name}
          </button>
        ))}
      </div>
      {canEdit && (
        <button
          disabled={!canPlace(canEdit, lights.length)}
          onClick={() => {
            const r = placeLight(lights, floorId, (sq.minX + sq.maxX) / 2, (sq.minY + sq.maxY) / 2, sq, canEdit);
            if (r.id) {
              onChange(r.lights);
              onSelect(r.id);
            }
          }}
        >
          {lights.length >= MAX_LIGHTS ? `Add light source (${lights.length}/${MAX_LIGHTS})` : "Add light source"}
        </button>
      )}
      <svg
        width={S}
        height={S}
        viewBox={`0 0 ${S} ${S}`}
        tabIndex={0}
        role="group"
        aria-label={`Light plan, square view of the floor. ${canEdit ? "Use Add light source, drag a marker to move it, arrow keys move the selected light, Delete removes it." : "Read only."}`}
        style={{ background: "#16181d", border: "1px solid #444", cursor: "default", touchAction: "none", maxWidth: "100%" }}
        onPointerDown={() => onSelect(null)}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const [x, y] = at(e);
          onChange(moveLight(lights, drag.current, x, y, sq, canEdit));
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onKeyDown={(e) => {
          if (!sel || !canEdit) return;
          const step = arrowStep(e.key, e.shiftKey);
          if (step) {
            e.preventDefault();
            onChange(nudgeLight(lights, sel.id, step[0], step[1], sq, canEdit));
          } else if (e.key === "Delete" || e.key === "Backspace") {
            e.preventDefault();
            onChange(lights.filter((l) => l.id !== sel.id));
            onSelect(null);
          }
        }}
      >
        {data?.model.boundaries.map((b, i) => (
          <polygon key={`b${i}`} points={b.polygon.map(([x, y]) => pt(x, y)).join(" ")} fill="rgba(70,110,200,0.12)" stroke="rgba(70,110,200,0.5)" strokeWidth={0.8} />
        ))}
        {data?.model.rooms?.map((r) => (
          <polygon key={r.id} points={r.polygon.map(([x, y]) => pt(x, y)).join(" ")} fill="none" stroke="rgba(200,200,200,0.25)" strokeWidth={0.6} strokeDasharray="3 3" />
        ))}
        {data?.model.walls.map((w) => (
          <polygon key={w.id} points={wallCorners(w).map(([x, y]) => pt(x, y)).join(" ")} fill="rgba(217,83,79,0.35)" />
        ))}
        {mine.map((l) => {
          const [cx, cy] = planToScreen(f, l.x_mm, l.y_mm);
          const on = l.id === selectedId;
          return (
            <g
              key={l.id}
              onPointerDown={(e) => {
                e.stopPropagation();
                onSelect(l.id);
                if (canEdit) {
                  drag.current = l.id;
                  e.currentTarget.setPointerCapture(e.pointerId);
                }
              }}
              style={{ cursor: canEdit ? "grab" : "pointer" }}
            >
              <circle cx={cx} cy={cy} r={on ? 9 : 6} fill={l.color} stroke={on ? "#fff" : "#000"} strokeWidth={on ? 2.5 : 1} />
              {l.kind === "spot" && <circle cx={cx} cy={cy} r={2} fill="#000" />}
              <title>{`${l.kind} ${l.id}`}</title>
            </g>
          );
        })}
      </svg>
      {sel && sel.floor_id === floorId && (
        <div>
          <label>
            Plan x (mm){" "}
            <CoordInput key={`x-${sel.id}-${sel.x_mm}`} label="Light x" value={sel.x_mm} disabled={!canEdit} onCommit={(t) => onChange(commitCoord(lights, sel.id, "x", t, sq, canEdit).lights)} />
          </label>{" "}
          <label>
            y (mm){" "}
            <CoordInput key={`y-${sel.id}-${sel.y_mm}`} label="Light y" value={sel.y_mm} disabled={!canEdit} onCommit={(t) => onChange(commitCoord(lights, sel.id, "y", t, sq, canEdit).lights)} />
          </label>
        </div>
      )}
      {loaded?.key === key && loaded.error && <div role="alert">Plan unavailable: {loaded.error}. Lights can still be placed by the x and y fields.</div>}
      <div>
        {lights.length}/{MAX_LIGHTS} lights, {mine.length} on this floor. {canEdit ? "" : "Read only."}
      </div>
    </div>
  );
}
