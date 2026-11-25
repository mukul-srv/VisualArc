"use client";

import { useEffect, useState } from "react";
import { addFloorJob, draftJob, generateJob, STAGE_LABEL, type DraftResult, type JobProgress } from "@/lib/jobs";
import { useRouter } from "next/navigation";
import { createProject, getPresets, getProject, importIfc, isGenerationId, splitUpload, uploadDxf, type Failure, type Issue, type Preflight, type Presets } from "@/lib/api";
import { parseManifest, viewerUrl, type Floor } from "@/lib/project";
import { DEFAULT_CONVENTIONS, getProjectConventions, inspectLayers, listConventions, putProjectConventions, type ConventionsSpec, type LayerRole, type PresetInfo } from "@/lib/conventions";
import { buildRequest, unitsDoubtful, unresolvable, type FormValues } from "@/lib/params";
import { changeTarget, EMPTY_FORM, NO_TARGET, resetForNewFile, restoredFromCache, reviewKey, reviewStale, targetAfterCreate, uploadStep } from "@/lib/upload-state";
import { HELP } from "@/lib/help";
import { focusSelector, type FixAction } from "@/lib/issues";
import { buildSplitRequest, initialRows, type SplitRow } from "@/lib/split";
import { AppNav } from "./AppNav";
import { Breadcrumbs } from "./Breadcrumbs";
import { ConventionsPanel } from "./ConventionsPanel";
import { IssueList } from "./IssueList";
import { ReviewPanel } from "./ReviewPanel";
import { UploadForm } from "./UploadForm";

export function UploadFlow() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobProgress | null>(null);
  const [pre, setPre] = useState<Preflight | null>(null);
  const [form, setForm] = useState<FormValues>(EMPTY_FORM);
  const [errors, setErrors] = useState<string[]>([]);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [blockedIssues, setBlockedIssues] = useState<Issue[] | null>(null);
  const [rows, setRows] = useState<SplitRow[]>([]);
  const [projectName, setProjectName] = useState("");
  const [proj, setProj] = useState(NO_TARGET);
  const [review, setReview] = useState<{ draft: DraftResult; key: string } | null>(null);

  const [presets, setPresets] = useState<Presets | null>(null);
  const [conv, setConv] = useState<ConventionsSpec>(DEFAULT_CONVENTIONS);
  const [convInfo, setConvInfo] = useState<{ presets: PresetInfo[]; roles: string[] } | null>(null);
  const [layers, setLayers] = useState<LayerRole[]>([]);
  // back/forward cache: the restored page still shows the previous file name; start over
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => restoredFromCache(e) && window.location.reload();
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);
  useEffect(() => {
    getPresets().then((r) => r.ok && setPresets(r.presets)); // placeholders only; the backend applies them
    listConventions().then((r) => r.ok && setConvInfo({ presets: r.presets, roles: r.roles }));
  }, []);

  // /new?project=<id> (Add floor on the project page or dashboard): add to that project
  const [addingTo, setAddingTo] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("project");
    if (!id || !isGenerationId(id)) return;
    getProject(id).then((r) => {
      const m = r.ok ? parseManifest(r.manifest) : null;
      if (!m) return setFailure(r.ok ? { ok: false, kind: "error", message: "Malformed project.", issues: [] } : r);
      setAddingTo({ id, name: m.name });
      setProj((p) => ({ ...p, on: true, target: id }));
    });
  }, []);

  // An existing project target brings its saved conventions along (also for a new file).
  const uploadId = pre?.upload_id;
  useEffect(() => {
    const t = proj.target.trim();
    if (proj.on && isGenerationId(t))
      getProjectConventions(t).then((r) => {
        if (r.ok) applyConventions({ preset: r.preset, mapping: r.mapping }, uploadId);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the target or file changes
  }, [proj.on, proj.target, uploadId]);

  // The chosen unit changes how the drawing is read (its size, the floors found): read it again.
  useEffect(() => {
    if (uploadId) applyConventions(conv, uploadId, form.units);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the unit changes
  }, [form.units]);

  // Changing the target clears what depended on the old one (elevation default, conventions).
  function changeProj(next: typeof proj) {
    const r = changeTarget(proj, next);
    setProj(r.proj);
    setErrors([]);
    if (r.resetConventions) applyConventions(DEFAULT_CONVENTIONS);
  }
  // Re-run the preflight under the chosen conventions: the mapping can resolve blocking issues.
  async function applyConventions(spec: ConventionsSpec, uploadId = pre?.upload_id, units = form.units) {
    setConv(spec);
    if (!uploadId || pre?.kind === "ifc") return; // layers and units are DXF-only
    const r = await inspectLayers(uploadId, spec, fetch, units || undefined);
    if (!r.ok) return setFailure(r);
    setFailure(null);
    setBlockedIssues(null); // a 409 from an earlier attempt no longer applies under new conventions
    setLayers(r.layers);
    setPre((cur) => (cur && cur.upload_id === uploadId ? { ...cur, issues: r.issues, needs: r.needs, floor_candidates: r.floor_candidates } : cur));
    setRows((cur) => (cur.length === r.floor_candidates.length ? cur : initialRows(r.floor_candidates)));
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setPre(null);
    setFailure(null);
    setBlockedIssues(null);
    setReview(null);
    setErrors([]);
    // everything typed or chosen for the previous file goes; a ?project= target stays
    const fresh = resetForNewFile(proj, addingTo !== null);
    setForm(fresh.form);
    setProjectName(fresh.projectName);
    setProj(fresh.proj);
    setLayers([]);
    const r = await uploadDxf(file);
    setBusy(false);
    if (r.ok) {
      setPre(r);
      setRows(initialRows(r.floor_candidates ?? []));
      setConv(DEFAULT_CONVENTIONS);
      // an existing project's conventions are loaded by the effect above instead
      if (r.kind !== "ifc" && !(fresh.proj.on && isGenerationId(fresh.proj.target.trim()))) applyConventions(DEFAULT_CONVENTIONS, r.upload_id);
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
    const r = await splitUpload(pre.upload_id, { ...req.body, conventions: conv });
    setBusy(false);
    if (r.ok) router.push(`/viewer?project=${r.project_id}`);
    else if (r.kind === "blocked") setBlockedIssues(r.issues);
    else setFailure(r);
  }

  async function onImportIfc() {
    if (!pre) return;
    if (!projectName.trim()) return setErrors(["Project name is required."]);
    setErrors([]);
    setFailure(null);
    setBusy(true);
    const r = await importIfc(pre.upload_id, projectName.trim());
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
        setProj((p) => targetAfterCreate(p, pid)); // a retry joins this project, it does not create another
      }
      target = pid;
      // always saved on the project (a reset to AIA included), so this and later floors use them
      const saved = await putProjectConventions(pid, conv);
      if (!saved.ok) {
        setBusy(false);
        return setFailure(saved);
      }
      r = await addFloorJob(pid, { ...req.params, floor_name: proj.floorName.trim(), ...(elev === undefined ? {} : { elevation: elev }) }, setJob);
      if (r.ok) setProj({ ...proj, target: pid }); // keep the id so the next floor joins it
    } else r = await generateJob({ ...req.params, conventions: conv }, setJob);
    setBusy(false);
    setJob(null);
    if (r.ok) router.push("floor" in r ? viewerUrl(target, (r.floor as Floor).id) : `/viewer?generation=${r.generation_id}`);
    else if (r.kind === "blocked") setBlockedIssues(r.issues);
    else setFailure(r);
  }

  const inputs = { form, rows, conv, projectName, proj };
  // Review: a draft read of the upload that stores nothing; Accept runs the normal generate/split calls.
  async function onReview() {
    if (!pre) return;
    const split = (pre.floor_candidates?.length ?? 0) >= 2;
    let body;
    if (split) {
      const req = buildSplitRequest(pre, form, rows, projectName);
      if (!req.ok) return setErrors(req.errors);
      const { project_name: _name, ...rest } = req.body; // the draft names no project
      void _name;
      body = { ...rest, conventions: conv };
    } else {
      const req = buildRequest(pre, form);
      if (!req.ok) return setErrors(req.errors);
      const { upload_id: _id, ...rest } = req.params; // the URL names the upload
      void _id;
      body = { ...rest, conventions: conv };
    }
    setErrors([]);
    setFailure(null);
    setBlockedIssues(null);
    setBusy(true);
    const r = await draftJob(pre.upload_id, body, setJob);
    setBusy(false);
    setJob(null);
    if (r.ok) setReview({ draft: r, key: reviewKey(inputs) });
    else setFailure(r);
  }

  // Fix action: open what hides the control, then focus it (after React has rendered the open state).
  function onFix(a: FixAction) {
    const el = document.querySelector<HTMLElement>(focusSelector(a));
    for (let d = el?.closest("details"); d; d = d.parentElement?.closest("details") ?? null) d.open = true;
    el?.focus();
    el?.scrollIntoView?.({ block: "center" });
  }

  const splitting = (pre?.floor_candidates?.length ?? 0) >= 2;
  const setRow = (i: number, patch: Partial<SplitRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const shown = blockedIssues ?? pre?.issues ?? [];
  const blocked = unresolvable(shown, unitsDoubtful({ issues: shown }));

  return (
    <main style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px", font: "15px system-ui" }}>
      <AppNav />
      <Breadcrumbs trail={addingTo
        ? [{ label: "Dashboard", href: "/" }, { label: addingTo.name, href: `/projects/${addingTo.id}` }, { label: "Add floor" }]
        : [{ label: "Dashboard", href: "/" }, { label: "New project" }]} />
      <h1>{addingTo ? `Add a floor to ${addingTo.name}` : "Floor plan (DXF or IFC) to 3D"}</h1>
      <p role="status"><strong>{uploadStep(pre !== null, busy, addingTo !== null)}</strong></p>
      <p><small>Values your drawing lacks use defaults, and every one is reported as assumed.</small></p>
      <input type="file" accept=".dxf,.ifc" autoComplete="off" disabled={busy} onChange={(e) => onFile(e.target.files?.[0])} />
      {busy && (
        <p role="status">
          {job && "Large drawings can take a minute; keep this page open. "}
          {job ? `${STAGE_LABEL[job.stage] ?? job.stage} (${job.progress}%)` : "Working…"}
          {job && <progress max={100} value={job.progress} style={{ marginLeft: 8 }} />}
        </p>
      )}
      {failure && (
        <p role="alert" style={{ color: "#b00020" }}>
          <strong>{failure.kind === "rejected" ? "File rejected:" : "Error:"}</strong> {failure.message}
        </p>
      )}
      {pre?.kind === "ifc" && (
        <>
          <h2>What we found</h2>
          <IssueList issues={shown} />
          <p>Storeys (each becomes a floor; names, elevations and sizes come from the file):</p>
          <ul>{(pre.storeys ?? []).map((s) => <li key={s.key}>{s.name}{s.elevation === null ? "" : `, elevation ${s.elevation} mm`}</li>)}</ul>
          {errors.map((e) => <p key={e} role="alert" style={{ color: "#b00020" }}>{e}</p>)}
          <label>Project name <input value={projectName} maxLength={100} onChange={(e) => setProjectName(e.target.value)} /></label>{" "}
          <button disabled={busy || shown.some((i) => i.severity === "blocking")} onClick={onImportIfc}>Import IFC</button>
          {shown.some((i) => i.severity === "blocking") && <p>Fix the blocking issues in the file and upload it again.</p>}
        </>
      )}
      {pre && pre.kind !== "ifc" && (
        <>
          <h2>What we found</h2>
          <IssueList issues={shown} />
          {convInfo && (
            <details>
              <summary title={HELP.conventions}>Layer conventions (advanced): {pre.inventory.layers.length} layers in this drawing</summary>
              <p><small>Layers: {pre.inventory.layers.join(", ")}</small></p>
              <ConventionsPanel spec={conv} setSpec={applyConventions} presets={convInfo.presets} roles={convInfo.roles} layers={layers} disabled={busy} />
            </details>
          )}
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
            setProj={changeProj}
            errors={errors}
            disabled={busy || blocked.length > 0}
            onSubmit={onReview}
          />
          {review && <ReviewPanel draft={review.draft} stale={reviewStale(review.key, inputs)} busy={busy} onFix={onFix} onRerun={onReview} onAccept={splitting ? onSplit : onGenerate} />}
          {blocked.length > 0 && <p>Fix the blocking issues in the drawing and upload it again.</p>}
        </>
      )}
    </main>
  );
}
