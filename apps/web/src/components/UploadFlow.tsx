"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { generate, uploadDxf, type Failure, type Issue, type Preflight } from "@/lib/api";
import { buildRequest, ceilingReady, setCeilingHeight, setWallHeight, splitIssues, UNITS, type FormValues } from "@/lib/params";
import { IssueList } from "./IssueList";

const EMPTY: FormValues = { wallHeight: "", ceilingHeight: "", ceilingConfirmed: false, units: "", doorHeight: "", windowHeight: "", windowSill: "" };
// Blocking issues the parameter form itself resolves; they must not lock the button.
const FORM_RESOLVABLE = ["wall_height_missing", "ceiling_height_missing", "units_missing"];

export function UploadFlow() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [pre, setPre] = useState<Preflight | null>(null);
  const [form, setForm] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<string[]>([]);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [blockedIssues, setBlockedIssues] = useState<Issue[] | null>(null);

  const field = (k: Exclude<keyof FormValues, "ceilingConfirmed">, label: string, hint = "") => (
    <label style={{ display: "block", margin: "6px 0" }}>
      {label}{" "}
      <input
        value={form[k] as string}
        inputMode="decimal"
        onChange={(e) =>
          setForm(
            k === "wallHeight"
              ? setWallHeight(form, e.target.value)
              : k === "ceilingHeight"
                ? setCeilingHeight(form, e.target.value)
                : { ...form, [k]: e.target.value },
          )
        }
      />{" "}
      {hint}
    </label>
  );

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setPre(null);
    setFailure(null);
    setBlockedIssues(null);
    setErrors([]);
    const r = await uploadDxf(file);
    setBusy(false);
    if (r.ok) setPre(r);
    else setFailure(r);
  }

  async function onGenerate() {
    if (!pre) return;
    const req = buildRequest(pre, form);
    if (!req.ok) {
      setErrors(req.errors);
      return;
    }
    setErrors([]);
    setFailure(null);
    setBlockedIssues(null);
    setBusy(true);
    const r = await generate(req.params);
    setBusy(false);
    if (r.ok) router.push(`/viewer?generation=${r.generation_id}`);
    else if (r.kind === "blocked") setBlockedIssues(r.issues);
    else setFailure(r);
  }

  const shown = blockedIssues ?? pre?.issues ?? [];
  const unresolvable = splitIssues(shown).blocking.filter((i) => !FORM_RESOLVABLE.includes(i.code));

  return (
    <main style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px", font: "15px system-ui" }}>
      <h1>DXF floor plan to 3D</h1>
      <p>Upload a DXF drawn to the supported convention. Nothing is guessed: missing values are asked for.</p>
      <input type="file" accept=".dxf" disabled={busy} onChange={(e) => onFile(e.target.files?.[0])} />
      {busy && <p role="status">Working…</p>}
      {failure && (
        <p role="alert" style={{ color: "#b00020" }}>
          <strong>{failure.kind === "rejected" ? "File rejected:" : "Error:"}</strong> {failure.message}
        </p>
      )}
      {pre && (
        <>
          <h2>Preflight</h2>
          <p>Layers: {pre.inventory.layers.join(", ")}</p>
          <IssueList issues={shown} />
          <h2>Parameters</h2>
          {field("wallHeight", "Wall height (mm)", pre.needs.includes("wall_height") ? "required" : "")}
          {field("ceilingHeight", "Ceiling height (mm)", pre.needs.includes("ceiling_height") ? "required" : "")}
          {form.ceilingHeight.trim() !== "" && (
            <label style={{ display: "block", margin: "6px 0" }}>
              <input
                type="checkbox"
                checked={form.ceilingConfirmed}
                onChange={(e) => setForm({ ...form, ceilingConfirmed: e.target.checked })}
              />{" "}
              I confirm the ceiling height is {form.ceilingHeight} mm (prefilled from the wall height; not assumed)
            </label>
          )}
          <label style={{ display: "block", margin: "6px 0" }}>
            Drawing units{" "}
            <select value={form.units} onChange={(e) => setForm({ ...form, units: e.target.value })}>
              <option value="">{pre.needs.includes("units") ? "select (required)" : "from DXF header"}</option>
              {UNITS.map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </label>
          {field("doorHeight", "Door height (mm)", "optional, else provisional default")}
          {field("windowHeight", "Window height (mm)", "optional, else provisional default")}
          {field("windowSill", "Window sill (mm)", "optional, else provisional default")}
          {errors.length > 0 && (
            <ul role="alert" style={{ color: "#b00020" }}>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <button disabled={busy || unresolvable.length > 0 || !ceilingReady(pre, form)} onClick={onGenerate}>
            Generate 3D model
          </button>
          {unresolvable.length > 0 && <p>Fix the blocking issues in the drawing and upload it again.</p>}
        </>
      )}
    </main>
  );
}
