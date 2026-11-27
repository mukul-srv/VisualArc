"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { deleteGeneration, deleteProject, listProjects, recentGenerations, renameGeneration, saveAsProject, type ProjectSummary, type RecentGeneration } from "../lib/projects";
import { AppNav } from "./AppNav";
import { ProjectList, RecentList } from "./lists";
import styles from "./dashboard.module.css";

export function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [recent, setRecent] = useState<RecentGeneration[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [listFailed, setListFailed] = useState(false);
  const [recentFailed, setRecentFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleted, setDeleted] = useState(false); // arrived from deleting a project

  const router = useRouter();
  const reload = () => {
    setListFailed(false);
    setRecentFailed(false);
    listProjects().then((r) => (r.ok ? setProjects(r.items) : (setListFailed(true), setProjects(null))));
    recentGenerations().then((r) => (r.ok ? setRecent(r.items) : setRecentFailed(true)));
  };
  useEffect(() => {
    queueMicrotask(reload);
    queueMicrotask(() => setDeleted(new URLSearchParams(window.location.search).has("deleted")));
  }, []);
  async function act(call: () => Promise<{ ok: boolean; message?: string }>, then: () => void) {
    setBusy(true);
    setError(null);
    const r = await call();
    setBusy(false);
    if (r.ok) then();
    else setError(r.message ?? "failed");
  }
  return (
    <main className={styles.page}>
      <AppNav />
      <h1>My projects</h1>
      {deleted && <p role="status">Project deleted.</p>}
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      {projects === null && !listFailed && <p role="status">Loading…</p>}
      {listFailed && (
        <div role="alert" className={styles.error}>
          <p>Could not load your projects.</p>
          <button type="button" onClick={reload}>Try again</button>
        </div>
      )}
      {projects && <ProjectList projects={projects} busy={busy} onDelete={(p) => act(() => deleteProject(p.id), reload)} />}
      <h2>Recent buildings</h2>
      {recentFailed && (
        <div role="alert" className={styles.error}>
          <p>Could not load recent buildings.</p>
          <button type="button" onClick={reload}>Try again</button>
        </div>
      )}
      <RecentList items={recent} busy={busy}
        onRename={(gid, name) => act(() => renameGeneration(gid, name), reload)}
        onDelete={(gid) => act(() => deleteGeneration(gid), reload)}
        onSave={async (gid, name) => {
          setBusy(true);
          setError(null);
          const r = await saveAsProject(gid, name);
          setBusy(false);
          if (r.ok) router.push(`/projects/${String(r.project_id)}`);
          else setError(r.message);
        }} />
    </main>
  );
}
