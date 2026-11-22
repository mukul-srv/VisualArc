"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listProjects, recentGenerations, type ProjectSummary, type RecentGeneration } from "../lib/projects";
import { ProjectList, RecentList } from "./lists";
import styles from "./dashboard.module.css";

export function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [recent, setRecent] = useState<RecentGeneration[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    listProjects().then((r) => (r.ok ? setProjects(r.items) : setError(r.message)));
    recentGenerations().then((r) => r.ok && setRecent(r.items));
  }, []);
  return (
    <main className={styles.page}>
      <div className={styles.head}>
        <h1>My projects</h1>
        <Link href="/new">New project</Link>
      </div>
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      {projects === null && !error && <p role="status">Loading…</p>}
      {projects && <ProjectList projects={projects} />}
      <h2>Recent buildings</h2>
      <RecentList items={recent} />
    </main>
  );
}
