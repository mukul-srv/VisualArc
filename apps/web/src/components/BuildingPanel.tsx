"use client";

import { useCallback, useEffect, useState } from "react";
import { confirmPairing, getBuilding, pairRows, setOffset, unpair, unpairedStairs, type Building } from "../lib/building";
import styles from "./dashboard.module.css";

// Floors as one building: per-floor plan offset (mm, a pure translation) and the stair pairings.
export function BuildingPanel({ projectId, readOnly, onChanged }: { projectId: string; readOnly: boolean; onChanged: () => void }) {
  const [b, setB] = useState<Building | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Record<string, { x: string; y: string }>>({});
  const [repair, setRepair] = useState<Record<string, string>>({}); // "floor/stair" -> chosen upper stair

  const load = useCallback(async () => {
    const r = await getBuilding(projectId);
    if (r.ok) setB(r.building);
    else setError(r.message);
  }, [projectId]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function act(call: () => Promise<{ ok: boolean; message?: string }>) {
    setBusy(true);
    setError(null);
    const r = await call();
    setBusy(false);
    if (!r.ok) return setError(r.message ?? "failed");
    await load();
    onChanged();
  }

  if (!b) return error ? <p role="alert" className={styles.error}>{error}</p> : <p role="status">Loading…</p>;
  const next = (id: string) => b.floors[b.floors.findIndex((f) => f.id === id) + 1];
  return (
    <div>
      <p>
        {b.stats.floor_count} floors, {b.stats.room_count} rooms, {(b.stats.total_area_mm2 / 1e6).toFixed(1)} m², height {(b.stats.height_mm / 1000).toFixed(2)} m.
      </p>
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      <h3>Floor offsets</h3>
      <p><small>Floors share the drawing origin. If a floor sits in the wrong place, shift its plan by X/Y mm (default 0). Only the position changes, never a measurement.</small></p>
      <ul>
        {b.floors.map((f) => {
          const d = draft[f.id] ?? { x: String(f.offset.x), y: String(f.offset.y) };
          const x = Number(d.x), y = Number(d.y);
          const bad = d.x.trim() === "" || d.y.trim() === "" || !Number.isFinite(x) || !Number.isFinite(y);
          return (
            <li key={f.id} className={styles.row}>
              <span>{f.name} ({f.offset.source === "user_provided" ? "set by you" : "default"})</span>
              <label>X mm <input aria-label={`${f.name} offset X`} value={d.x} disabled={readOnly} onChange={(e) => setDraft({ ...draft, [f.id]: { ...d, x: e.target.value } })} /></label>
              <label>Y mm <input aria-label={`${f.name} offset Y`} value={d.y} disabled={readOnly} onChange={(e) => setDraft({ ...draft, [f.id]: { ...d, y: e.target.value } })} /></label>
              {!readOnly && <button disabled={busy || bad || (x === f.offset.x && y === f.offset.y)} onClick={() => act(() => setOffset(projectId, f.id, x, y))}>Set offset</button>}
            </li>
          );
        })}
      </ul>
      <h3>Stair pairs</h3>
      {pairRows(b).length === 0 && <p>No stairs are paired.</p>}
      <ul>
        {pairRows(b).map((r) => (
          <li key={r.key} className={styles.row}>
            <span>{r.label}: {r.status}{r.status !== "rejected" && ` (${r.overlapPct}% overlap)`}</span>
            {!readOnly && r.status === "auto" && <button disabled={busy} onClick={() => act(() => confirmPairing(projectId, r.ref))}>Accept</button>}
            {!readOnly && r.status !== "rejected" && <button disabled={busy} onClick={() => act(() => unpair(projectId, r.ref))}>Unpair</button>}
            {!readOnly && r.status === "rejected" && <button disabled={busy} onClick={() => act(() => confirmPairing(projectId, r.ref))}>Pair again</button>}
          </li>
        ))}
      </ul>
      {!readOnly && b.floors.map((f) => {
        const up = next(f.id);
        const free = unpairedStairs(b, f.id);
        if (!up || free.length === 0 || up.stairs.length === 0) return null;
        return free.map((s) => {
          const k = `${f.id}/${s}`;
          const pick = repair[k] ?? up.stairs[0].id;
          return (
            <div key={k} className={styles.row}>
              <span>{f.name} {s} is unpaired. Pair with {up.name}</span>
              <select aria-label={`Pair ${f.name} ${s}`} value={pick} onChange={(e) => setRepair({ ...repair, [k]: e.target.value })}>
                {up.stairs.map((u) => <option key={u.id} value={u.id}>{u.id}</option>)}
              </select>
              <button disabled={busy} onClick={() => act(() => confirmPairing(projectId, { lower_floor: f.id, lower_stair: s, upper_floor: up.id, upper_stair: pick }))}>Pair</button>
            </div>
          );
        });
      })}
      <h3>Building issues</h3>
      {b.issues.length === 0 ? <p>None.</p> : <ul>{b.issues.map((i, n) => <li key={n}>{i.severity}: {i.message}</li>)}</ul>}
    </div>
  );
}
