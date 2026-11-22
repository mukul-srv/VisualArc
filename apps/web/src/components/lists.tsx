"use client";

import Link from "next/link";
import { useState } from "react";
import { shortDate, type ProjectSummary, type RecentGeneration, type VersionInfo } from "../lib/projects";
import { viewerUrl, type Role } from "../lib/project";
import { can } from "./ProjectParts";
import styles from "./dashboard.module.css";

/** My projects (and those shared with me), newest first, each row with its actions by role:
 *  Open (all), Add floor (editor+), Share and Delete (owner). */
export function ProjectList({ projects, onDelete, busy }: { projects: ProjectSummary[]; onDelete?: (p: ProjectSummary) => void; busy?: boolean }) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (projects.length === 0)
    return (
      <p>
        No projects yet. <Link href="/new">Create your first project</Link> from a DXF floor plan.
      </p>
    );
  return (
    <table className={styles.table}>
      <caption className={styles.sr}>My projects</caption>
      <thead>
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Floors</th>
          <th scope="col">Version</th>
          <th scope="col">Updated</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => {
          const role = (p.role ?? "owner") as Role;
          const { edit, manage } = can(role);
          return (
            <tr key={p.id}>
              <td><Link href={`/projects/${p.id}`}>{p.name}</Link>{role !== "owner" ? ` (shared: ${role})` : ""}</td>
              <td>{p.floor_count}</td>
              <td>v{p.version}</td>
              <td>{shortDate(p.updated_at)}</td>
              <td>
                <span className={styles.actions}>
                  {p.floor_count > 0 ? <a href={viewerUrl(p.id)}>Open</a> : <span title="Add a floor first" aria-disabled="true">Open (no floors)</span>}
                  {edit && <Link href={`/new?project=${p.id}`}>Add floor</Link>}
                  {manage && <Link href={`/projects/${p.id}#sharing`}>Share</Link>}
                  {manage && onDelete && confirming !== p.id && (
                    <button type="button" disabled={busy} aria-label={`Delete ${p.name}`} onClick={() => setConfirming(p.id)}>Delete</button>
                  )}
                  {manage && onDelete && confirming === p.id && (
                    <span role="alertdialog" aria-label={`Confirm delete ${p.name}`}>
                      Delete &quot;{p.name}&quot;?{" "}
                      <button type="button" disabled={busy} onClick={() => { onDelete(p); setConfirming(null); }}>Confirm delete</button>{" "}
                      <button type="button" onClick={() => setConfirming(null)}>Cancel</button>
                    </span>
                  )}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Recent models. A standalone one (generated without a project) has no project page, so it cannot
 *  be shared, versioned or extended until it is saved as a project. */
export function RecentList({ items, onSave, busy }: { items: RecentGeneration[]; onSave?: (generationId: string, name: string) => void; busy?: boolean }) {
  const [saving, setSaving] = useState<{ id: string; name: string } | null>(null);
  if (items.length === 0) return <p>No buildings generated yet.</p>;
  return (
    <ul aria-label="Recent buildings">
      {items.map((g) => (
        <li key={g.generation_id}>
          <a href={g.project_id ? viewerUrl(g.project_id, g.floor_id ?? undefined) : `/viewer?generation=${g.generation_id}`}>
            {g.project_name ? `${g.project_name} / ${g.floor_name}` : `Model ${g.generation_id.slice(0, 8)}`}
          </a>{" "}
          <small>{shortDate(g.created_at)}</small>
          {!g.project_id && (
            <>
              {" "}<small>Standalone model: not in a project, so it cannot be shared or extended.</small>{" "}
              {onSave && saving?.id !== g.generation_id && (
                <button type="button" disabled={busy} onClick={() => setSaving({ id: g.generation_id, name: "" })}>Save as project</button>
              )}
              {onSave && saving?.id === g.generation_id && (
                <form style={{ display: "inline" }} onSubmit={(e) => { e.preventDefault(); onSave(g.generation_id, saving.name.trim()); setSaving(null); }}>
                  <input aria-label="Project name" placeholder="Project name" value={saving.name} maxLength={100} onChange={(e) => setSaving({ id: g.generation_id, name: e.target.value })} />{" "}
                  <button disabled={busy || !saving.name.trim()} title={saving.name.trim() ? undefined : "Enter a project name"}>Create project</button>{" "}
                  <button type="button" onClick={() => setSaving(null)}>Cancel</button>
                </form>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Newest first. Past versions open read-only in the viewer; restoring makes a new version. */
export function VersionList({ projectId, versions, onRestore, busy, readOnly }: { projectId: string; versions: VersionInfo[]; onRestore: (n: number) => void; busy?: boolean; readOnly?: boolean }) {
  const latest = versions[0]?.number;
  return (
    <ol reversed className={styles.versions} aria-label="Version history">
      {versions.map((v) => (
        <li key={v.number} value={v.number}>
          <strong>Version {v.number}</strong>: {v.message} ({v.floor_count} floors, {shortDate(v.created_at)}){" "}
          <a href={viewerUrl(projectId, undefined, v.number)}>View</a>{" "}
          {readOnly ? null : v.number === latest ? (
            <em>current</em>
          ) : (
            <button type="button" disabled={busy} aria-label={`Restore version ${v.number}`} onClick={() => onRestore(v.number)}>
              Restore
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}
