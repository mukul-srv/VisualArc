"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { addFloor, createProject, generate, getPresets, isGenerationId, splitUpload, uploadDxf, type Failure, type Issue, type Preflight, type Presets } from "@/lib/api";
import { viewerUrl, type Floor } from "@/lib/project";
import { buildRequest, splitIssues, type FormValues } from "@/lib/params";
import { buildSplitRequest, initialRows, type SplitRow } from "@/lib/split";
import { IssueList } from "./IssueList";
import { UploadForm } from "./UploadForm";

const EMPTY: FormValues = { buildingType: "residential", wallHeight: "", ceilingHeight: "", units: "", doorHeight: "", windowHeight: "", windowSill: "" };
// Blocking issues the parameter form itself resolves; they must not lock the button.
const FORM_RESOLVABLE = ["units_missing", "floor_split_unconfirmed"];

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

  const [presets, setPresets] = useState<Presets | null>(null);
  useEffect(() => {
    getPresets().then((r) => r.ok && setPresets(r.presets)); // placeholders only; the backend applies them
  }, []);

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
    const elev = proj.elevation.trim() === "" ? undefined : Number(proj.elevation);
    if (proj.on) {
      const errs = [];
      if (!proj.target.trim()) errs.push("Project: enter an existing project id or a new project name.");
      if (!proj.floorName.trim()) errs.push("Floor name is required.");
      if (elev !== undefined && !Number.isFinite(elev)) errs.push("Floor elevation (mm) must be a number, or empty for the default.");
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
      r = await addFloor(pid, { ...req.params, floor_name: proj.floorName.trim(), ...(elev === undefined ? {} : { elevation: elev }) });
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
      <p>Upload a DXF drawn to the supported convention. Values the drawing lacks use nominal defaults, and every one is reported as assumed.</p>
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
          <UploadForm
            pre={pre}
            form={form}
            setForm={setForm}
            presets={presets}
            rows={rows}
            setRow={setRow}
            projectName={projectName}
            setProjectName={setProjectName}
            proj={proj}
            setProj={setProj}
            errors={errors}
            disabled={busy || unresolvable.length > 0}
            onSubmit={splitting ? onSplit : onGenerate}
          />
          {unresolvable.length > 0 && <p>Fix the blocking issues in the drawing and upload it again.</p>}
        </>
      )}
    </main>
  );
}
