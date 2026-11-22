import Link from "next/link";
import { shortDate, type ProjectSummary, type RecentGeneration, type VersionInfo } from "../lib/projects";
import { viewerUrl } from "../lib/project";
import styles from "./dashboard.module.css";

/** My projects, newest first; an empty list shows the empty state. */
export function ProjectList({ projects }: { projects: ProjectSummary[] }) {
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
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => (
          <tr key={p.id}>
            <td><Link href={`/projects/${p.id}`}>{p.name}</Link></td>
            <td>{p.floor_count}</td>
            <td>v{p.version}</td>
            <td>{shortDate(p.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RecentList({ items }: { items: RecentGeneration[] }) {
  if (items.length === 0) return <p>No buildings generated yet.</p>;
  return (
    <ul aria-label="Recent buildings">
      {items.map((g) => (
        <li key={g.generation_id}>
          <a href={g.project_id ? viewerUrl(g.project_id, g.floor_id ?? undefined) : `/viewer?generation=${g.generation_id}`}>
            {g.project_name ? `${g.project_name} / ${g.floor_name}` : `Model ${g.generation_id.slice(0, 8)}`}
          </a>{" "}
          <small>{shortDate(g.created_at)}</small>
        </li>
      ))}
    </ul>
  );
}

/** Newest first. Past versions open read-only in the viewer; restoring makes a new version. */
export function VersionList({ projectId, versions, onRestore, busy }: { projectId: string; versions: VersionInfo[]; onRestore: (n: number) => void; busy?: boolean }) {
  const latest = versions[0]?.number;
  return (
    <ol reversed className={styles.versions} aria-label="Version history">
      {versions.map((v) => (
        <li key={v.number} value={v.number}>
          <strong>Version {v.number}</strong>: {v.message} ({v.floor_count} floors, {shortDate(v.created_at)}){" "}
          <a href={viewerUrl(projectId, undefined, v.number)}>View</a>{" "}
          {v.number === latest ? (
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
