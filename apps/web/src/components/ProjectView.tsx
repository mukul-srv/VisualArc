"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getProject } from "../lib/api";
import { parseManifest, sortFloors, viewerUrl, type Manifest } from "../lib/project";
import { deleteProject, listVersions, renameProject, restoreVersion, type VersionInfo } from "../lib/projects";
import { ConventionsPanel } from "./ConventionsPanel";
import { getProjectConventions, listConventions, putProjectConventions, type ConventionsSpec, type PresetInfo } from "../lib/conventions";
import { AccessPanel } from "./AccessPanel";
import { VersionList } from "./lists";
import styles from "./dashboard.module.css";

type Outcome = { ok: boolean; message?: string };

export function ProjectView({ id }: { id: string }) {
  const router = useRouter();
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
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
        {error ? <p role="alert" className={styles.error}>{error}</p> : <p role="status">Loading…</p>}
        <Link href="/">All projects</Link>
      </main>
    );
  const role = manifest.role ?? "owner";
  const canEdit = role !== "viewer";
  return (
    <main className={styles.page}>
      <p><Link href="/">All projects</Link></p>
      <h1>{manifest.name}</h1>
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      {!canEdit && <p>You have view-only access to this project.</p>}
      {canEdit && <form className={styles.row} onSubmit={(e) => { e.preventDefault(); run(() => renameProject(id, name.trim()), load); }}>
        <label>Project name <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></label>
        <button disabled={busy || !name.trim() || name.trim() === manifest.name}>Rename</button>
      </form>}
      <h2>Floors</h2>
      {manifest.floors.length === 0 ? <p>No floors yet.</p> : (
        <ul>
          {sortFloors(manifest.floors).map((f) => (
            <li key={f.id}>{f.name} at {f.elevation.value} mm <a href={viewerUrl(id, f.id)}>Open in viewer</a></li>
          ))}
        </ul>
      )}
      {conv && convInfo && (
        <>
          <h2>Layer conventions</h2>
          <ConventionsPanel spec={conv} setSpec={setConv} presets={convInfo.presets} roles={convInfo.roles} layers={[]} disabled={busy} readOnly={!canEdit} />
          {canEdit && <button type="button" disabled={busy} onClick={() => run(() => putProjectConventions(id, conv), load)}>Save conventions</button>}
          <p><small>Applies to floors added from now on; existing floors are not regenerated.</small></p>
        </>
      )}
      <h2>Version history</h2>
      <VersionList projectId={id} versions={versions} busy={busy} onRestore={(n) => run(() => restoreVersion(id, n), load)} readOnly={!canEdit} />
      {role === "owner" && <AccessPanel projectId={id} />}
      {role === "owner" && <>
      <h2>Delete</h2>
      {confirming ? (
        <div role="alertdialog" aria-label="Confirm delete" className={styles.row}>
          <span>Delete &quot;{manifest.name}&quot;? It disappears from your list; stored files are kept.</span>
          <button disabled={busy} onClick={() => run(() => deleteProject(id), () => router.push("/"))}>Confirm delete</button>
          <button type="button" onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button type="button" onClick={() => setConfirming(true)}>Delete project</button>
      )}
      </>}
    </main>
  );
}
