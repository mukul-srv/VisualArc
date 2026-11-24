"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getProject } from "../lib/api";
import { parseManifest, type Manifest } from "../lib/project";
import { deleteProject, listVersions, removeFloor, renameFloor, renameProject, restoreVersion, type VersionInfo } from "../lib/projects";
import { ConventionsPanel } from "./ConventionsPanel";
import { getProjectConventions, listConventions, putProjectConventions, type ConventionsSpec, type PresetInfo } from "../lib/conventions";
import { AccessPanel } from "./AccessPanel";
import { HELP } from "../lib/help";
import { BuildingPanel } from "./BuildingPanel";
import { PlanEditor } from "./PlanEditor";
import { PlanOverlay } from "./PlanOverlay";
import { ParametersPanel } from "./ParametersPanel";
import { AppNav } from "./AppNav";
import { Breadcrumbs } from "./Breadcrumbs";
import { VersionList } from "./lists";
import { can, FloorList, ProjectTabs, ProjectToolbar, tabsFor, type TabId } from "./ProjectParts";
import styles from "./dashboard.module.css";

type Outcome = { ok: boolean; message?: string };

export function ProjectView({ id }: { id: string }) {
  const router = useRouter();
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<TabId>("floors");
  const [editingPlan, setEditingPlan] = useState<string | null>(null); // floor id open in the plan editor
  const [convOpen, setConvOpen] = useState(false); // layer conventions fold, under Floors
  const [conv, setConv] = useState<ConventionsSpec | null>(null);
  const [convInfo, setConvInfo] = useState<{ presets: PresetInfo[]; roles: string[] } | null>(null);

  const load = useCallback(async () => {
    const [p, v] = await Promise.all([getProject(id), listVersions(id)]);
    const m = p.ok ? parseManifest(p.manifest) : null;
    if (!p.ok || !m) return setError(p.ok ? "Malformed project." : p.message);
    setManifest(m);
    setName(m.name);
    if (v.ok) setVersions(v.items);
    const [c, info] = await Promise.all([getProjectConventions(id), listConventions()]);
    if (c.ok) setConv({ preset: c.preset, mapping: c.mapping });
    if (info.ok) setConvInfo({ presets: info.presets, roles: info.roles });
  }, [id]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);
  // /projects/<id>#sharing (the dashboard's Share button) opens that section directly
  useEffect(() => {
    const t = window.location.hash.slice(1);
    if (t === "conventions") queueMicrotask(() => { setTab("floors"); setConvOpen(true); }); // old links: now a fold under Floors
    else if (["floors", "parameters", "versions", "sharing"].includes(t)) queueMicrotask(() => setTab(t as TabId));
  }, []);
  const select = (t: TabId) => {
    setTab(t);
    window.history.replaceState(null, "", `#${t}`);
  };

  async function run(call: () => Promise<Outcome>, then: () => void | Promise<void>) {
    setBusy(true);
    setError(null);
    const r = await call();
    setBusy(false);
    if (r.ok) await then();
    else setError(r.message ?? "failed");
  }

  if (!manifest)
    return (
      <main className={styles.page}>
        <AppNav />
        <Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "Project" }]} />
        {error ? <p role="alert" className={styles.error}>{error}</p> : <p role="status">Loading…</p>}
      </main>
    );
  const role = manifest.role ?? "viewer";
  const { edit, manage } = can(role);
  // a tab the role cannot see (e.g. #sharing for an editor) falls back to Floors
  const shown: TabId = tabsFor(role).some((t) => t.id === tab) ? tab : "floors";
  return (
    <main className={styles.page}>
      <AppNav />
      <Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: manifest.name }]} />
      <h1>{manifest.name}</h1>
      {!edit && <p>You have view-only access to this project.</p>}
      <ProjectToolbar id={id} role={role} floors={manifest.floors} busy={busy}
        onShare={() => select("sharing")} onRename={() => setRenaming(true)} onDelete={() => setConfirming(true)} />
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      {renaming && (
        <form className={styles.row} onSubmit={(e) => { e.preventDefault(); run(() => renameProject(id, name.trim()), () => { setRenaming(false); return load(); }); }}>
          <label>Project name <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></label>
          <button disabled={busy || !name.trim() || name.trim() === manifest.name} title={name.trim() === manifest.name ? "Change the name first" : undefined}>Save name</button>
          <button type="button" onClick={() => { setRenaming(false); setName(manifest.name); }}>Cancel</button>
        </form>
      )}
      {confirming && manage && (
        <div role="alertdialog" aria-label="Confirm delete" className={styles.row}>
          <span>Delete &quot;{manifest.name}&quot;? It disappears from every list (collaborators lose access); stored files are kept.</span>
          <button disabled={busy} onClick={() => run(() => deleteProject(id), () => router.push("/"))}>Confirm delete</button>
          <button type="button" onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      )}
      <ProjectTabs role={role} tab={shown} onSelect={select} />
      <section role="tabpanel" id={`panel-${shown}`} aria-labelledby={`tab-${shown}`}>
        {shown === "floors" && (
          <>
            <FloorList projectId={id} floors={manifest.floors} role={role} busy={busy}
              onRename={(fid, n) => run(() => renameFloor(id, fid, n), load)}
              onRemove={(fid) => { setEditingPlan(null); run(() => removeFloor(id, fid), load); }}
              onEditPlan={setEditingPlan} />
            {editingPlan && manifest.floors.some((f) => f.id === editingPlan) && (
              <PlanEditor projectId={id} floor={manifest.floors.find((f) => f.id === editingPlan)!} onSaved={load} onClose={() => setEditingPlan(null)} />
            )}
            <p><small>{edit ? "Use Edit plan on a floor to change its walls, doors, windows and room names, or fix the DXF and add it as a new floor." : "To change the geometry, fix the DXF and add it as a new floor."}</small></p>
            <details>
              <summary>Plan vs model (the drawing under what was built)</summary>
              <PlanOverlay projectId={id} floors={manifest.floors} />
            </details>
            {manifest.floors.length > 1 && (
              <details>
                <summary>Building: floor offsets and stair pairs</summary>
                <BuildingPanel projectId={id} readOnly={!edit} onChanged={load} />
              </details>
            )}
            {conv && convInfo && (
              <details open={convOpen} onToggle={(e) => setConvOpen((e.target as HTMLDetailsElement).open)}>
                <summary title={HELP.conventions}>Layer conventions (advanced)</summary>
                <ConventionsPanel spec={conv} setSpec={setConv} presets={convInfo.presets} roles={convInfo.roles} layers={[]} disabled={busy} readOnly={!edit} />
                {edit ? (
                  <button type="button" disabled={busy} onClick={() => run(() => putProjectConventions(id, conv), load)}>Save conventions</button>
                ) : (
                  <p>Only editors and the owner can change conventions.</p>
                )}
                <p><small>New layers are mapped when you upload a drawing (Add floor). Changes apply to floors added from now on; existing floors are not regenerated.</small></p>
              </details>
            )}
          </>
        )}
        {shown === "parameters" && <ParametersPanel key={id} projectId={id} readOnly={!edit} onChanged={load} />}
        {shown === "versions" && (
          <VersionList projectId={id} versions={versions} busy={busy} onRestore={(n) => run(() => restoreVersion(id, n), load)} readOnly={!edit} />
        )}
        {shown === "sharing" && manage && <AccessPanel projectId={id} />}
      </section>
    </main>
  );
}
