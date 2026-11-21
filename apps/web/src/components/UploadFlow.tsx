"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { addFloor, createProject, generate, isGenerationId, splitUpload, uploadDxf, type Failure, type Issue, type Preflight } from "@/lib/api";
import { viewerUrl, type Floor } from "@/lib/project";
import { buildRequest, ceilingReady, setCeilingHeight, setWallHeight, splitIssues, UNITS, type FormValues } from "@/lib/params";
import { bboxSize, buildSplitRequest, initialRows, type SplitRow } from "@/lib/split";
import { IssueList } from "./IssueList";

const EMPTY: FormValues = { wallHeight: "", ceilingHeight: "", ceilingConfirmed: false, units: "", doorHeight: "", windowHeight: "", windowSill: "" };
// Blocking issues the parameter form itself resolves; they must not lock the button.
const FORM_RESOLVABLE = ["wall_height_missing", "ceiling_height_missing", "units_missing", "floor_split_unconfirmed"];

export function UploadFlow() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [pre, setPre] = useState<Preflight | null>(null);
  const [form, setForm] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<string[]>([]);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [blockedIssues, setBlockedIssues] = useState<Issue[] | null>(null);
  const [rows, setRows] = useState<SplitRow[]>([]);
  const [projectName, setProjectName] = useState("");
  const [proj, setProj] = useState({ on: false, target: "", floorName: "", elevation: "" });

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
    if (r.ok) {
      setPre(r);
      setRows(initialRows(r.floor_candidates ?? []));
    } else setFailure(r);
  }

  async function onSplit() {
    if (!pre) return;
    const req = buildSplitRequest(pre, form, rows, projectName);
    if (!req.ok) return setErrors(req.errors);
    setErrors([]);
    setFailure(null);
    setBlockedIssues(null);
    setBusy(true);
    const r = await splitUpload(pre.upload_id, req.body);
    setBusy(false);
    if (r.ok) router.push(`/viewer?project=${r.project_id}`);
    else if (r.kind === "blocked") setBlockedIssues(r.issues);
    else setFailure(r);
  }

  async function onGenerate() {
    if (!pre) return;
    const req = buildRequest(pre, form);
    if (!req.ok) {
      setErrors(req.errors);
      return;
    }
    const elev = Number(proj.elevation);
    if (proj.on) {
      const errs = [];
      if (!proj.target.trim()) errs.push("Project: enter an existing project id or a new project name.");
      if (!proj.floorName.trim()) errs.push("Floor name is required.");
      if (proj.elevation.trim() === "" || !Number.isFinite(elev)) errs.push("Floor elevation (mm) is required and must be a number.");
      if (errs.length) return setErrors(errs);
    }
    setErrors([]);
    setFailure(null);
    setBlockedIssues(null);
    setBusy(true);
    let r;
    let target = "";
    if (proj.on) {
      const t = proj.target.trim();
      let pid = t;
      if (!isGenerationId(t)) {
        // not a project id: treat it as the name of a new project
        const c = await createProject(t);
        if (!c.ok) {
          setBusy(false);
          return setFailure(c);
        }
        pid = c.project_id;
      }
      target = pid;
      r = await addFloor(pid, { ...req.params, floor_name: proj.floorName.trim(), elevation: elev });
      if (r.ok) setProj({ ...proj, target: pid }); // keep the id so the next floor joins it
    } else r = await generate(req.params);
    setBusy(false);
    if (r.ok) router.push("floor" in r ? viewerUrl(target, (r.floor as Floor).id) : `/viewer?generation=${r.generation_id}`);
    else if (r.kind === "blocked") setBlockedIssues(r.issues);
    else setFailure(r);
  }

  const splitting = (pre?.floor_candidates?.length ?? 0) >= 2;
  const setRow = (i: number, patch: Partial<SplitRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
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
          {splitting && (
            <>
              <h2>Floors found in this drawing</h2>
              <p>
                Confirm each floor. Offsets (mm) move the floor so floors line up; they start from the floor&apos;s
                lower-left corner and are <em>proposed</em> until you confirm them. Excluded floors are reported as not
                reconstructed.
              </p>
              <label style={{ display: "block", margin: "6px 0" }}>
                Project name <input value={projectName} onChange={(e) => setProjectName(e.target.value)} />
              </label>
              <table>
                <thead>
                  <tr>
                    <th>Key</th><th>Size (mm)</th><th>Build</th><th>Name</th><th>Elevation (mm)</th><th>Offset X (mm)</th><th>Offset Y (mm)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const s = bboxSize(pre.floor_candidates![i]);
                    return (
                      <tr key={r.key}>
                        <td>{r.key}</td>
                        <td>{s.width.toFixed(0)} x {s.height.toFixed(0)}</td>
                        <td><input type="checkbox" aria-label={`Build ${r.key}`} checked={!r.exclude} onChange={(e) => setRow(i, { exclude: !e.target.checked })} /></td>
                        <td><input aria-label={`Name ${r.key}`} value={r.name} disabled={r.exclude} onChange={(e) => setRow(i, { name: e.target.value })} /></td>
                        <td><input aria-label={`Elevation ${r.key}`} inputMode="decimal" value={r.elevation} disabled={r.exclude} onChange={(e) => setRow(i, { elevation: e.target.value })} /></td>
                        <td><input aria-label={`Offset X ${r.key}`} inputMode="decimal" value={r.offsetX} disabled={r.exclude} onChange={(e) => setRow(i, { offsetX: e.target.value })} /> proposed</td>
                        <td><input aria-label={`Offset Y ${r.key}`} inputMode="decimal" value={r.offsetY} disabled={r.exclude} onChange={(e) => setRow(i, { offsetY: e.target.value })} /> proposed</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
          {!splitting && (
          <label style={{ display: "block", margin: "6px 0" }}>
            <input type="checkbox" checked={proj.on} onChange={(e) => setProj({ ...proj, on: e.target.checked })} /> Add to a project (multi-floor)
          </label>
          )}
          {!splitting && proj.on && (
            <>
              <label style={{ display: "block", margin: "6px 0" }}>
                Project id (existing) or name (new){" "}
                <input value={proj.target} onChange={(e) => setProj({ ...proj, target: e.target.value })} />
              </label>
              <label style={{ display: "block", margin: "6px 0" }}>
                Floor name <input value={proj.floorName} onChange={(e) => setProj({ ...proj, floorName: e.target.value })} />
              </label>
              <label style={{ display: "block", margin: "6px 0" }}>
                Floor elevation (mm){" "}
                <input inputMode="decimal" value={proj.elevation} onChange={(e) => setProj({ ...proj, elevation: e.target.value })} /> required, unique per project
              </label>
            </>
          )}
          {errors.length > 0 && (
            <ul role="alert" style={{ color: "#b00020" }}>
              {errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          <button disabled={busy || unresolvable.length > 0 || !ceilingReady(pre, form)} onClick={splitting ? onSplit : onGenerate}>
            {splitting ? "Confirm floors and generate" : "Generate 3D model"}
          </button>
          {unresolvable.length > 0 && <p>Fix the blocking issues in the drawing and upload it again.</p>}
        </>
      )}
    </main>
  );
}
