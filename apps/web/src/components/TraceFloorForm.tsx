"use client";

import { useState } from "react";
import { createTraceFloor } from "../lib/underlay";

/** Add an empty floor with a picture (PNG, JPEG or a PDF scan) to trace over. Nothing is detected from the picture. */
export function TraceFloorForm({ projectId, onCreated }: { projectId: string; onCreated: (floorId: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [elevation, setElevation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    const el = elevation.trim() === "" ? undefined : Number(elevation);
    if (!file) return setError("Choose a PNG, JPEG or PDF file.");
    if (!name.trim()) return setError("Floor name is required.");
    if (el !== undefined && !Number.isFinite(el)) return setError("Elevation (mm) must be a number, or empty for the default.");
    setError(null);
    setBusy(true);
    const r = await createTraceFloor(file, { projectId, floorName: name.trim(), elevation: el });
    setBusy(false);
    if (r.ok) {
      setFile(null);
      setName("");
      setElevation("");
      onCreated(r.floor.id);
    } else setError(r.message);
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label="Trace a floor from an image">
      <p><small>For a scan or photo of a plan: it becomes a picture under an empty floor. You set its scale with two points, then trace walls, doors and windows by hand. Nothing is detected from the picture.</small></p>
      <input type="file" accept="image/png,image/jpeg,application/pdf" disabled={busy} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />{" "}
      <label>Floor name <input value={name} maxLength={100} disabled={busy} onChange={(e) => setName(e.target.value)} /></label>{" "}
      <label>Elevation (mm) <input inputMode="decimal" size={8} placeholder="default" value={elevation} disabled={busy} onChange={(e) => setElevation(e.target.value)} /></label>{" "}
      <button disabled={busy}>{busy ? "Adding…" : "Add traced floor"}</button>
      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
    </form>
  );
}
