"use client";

import { useCallback, useEffect, useState } from "react";
import { changeParametersJob, STAGE_LABEL } from "../lib/jobs";
import { diffParameters, PARAM_LABEL, ROOF_TYPES, SOURCE_LABEL } from "../lib/parameters";
import { getParameters, type ProjectParam } from "../lib/projects";
import type { Issue } from "../lib/api";
import { IssueList } from "./IssueList";
import styles from "./dashboard.module.css";

// Project parameters with provenance. Saving regenerates every floor (a job) as one new version;
// emptying a user-specified field returns it to the preset default.
export function ParametersPanel({ projectId, readOnly, onChanged }: { projectId: string; readOnly: boolean; onChanged: () => void }) {
  const [loaded, setLoaded] = useState<Record<string, ProjectParam> | null>(null);
  const [text, setText] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]); // what the last regeneration reported
  const [saved, setSaved] = useState<number | null>(null); // version it produced

  const load = useCallback(async () => {
    const r = await getParameters(projectId);
    if (!r.ok) return setErrors([r.message]);
    const params: Record<string, ProjectParam> = {};
    for (const [k, v] of Object.entries(r)) if (k !== "ok") params[k] = v as ProjectParam;
    setLoaded(params);
    setText(Object.fromEntries(Object.entries(params).map(([k, p]) => [k, String(p.value)])));
  }, [projectId]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function save() {
    if (!loaded) return;
    const d = diffParameters(loaded, text);
    if (!d.ok) return setErrors(d.errors);
    if (!Object.keys(d.values).length) return setErrors(["Nothing changed."]);
    setErrors([]);
    setSaved(null);
    setBusy(true);
    const r = await changeParametersJob(projectId, d.values, (p) => setStatus(STAGE_LABEL[p.stage] ?? p.stage));
    setBusy(false);
    setStatus(null);
    if (!r.ok) return setErrors([r.message, ...r.issues.map((i) => i.message)]);
    setIssues(r.issues ?? []);
    setSaved(r.version ?? null);
    await load();
    onChanged();
  }

  if (!loaded) return errors.length ? <p role="alert" className={styles.error}>{errors[0]}</p> : <p role="status">Loading…</p>;
  return (
    <section aria-label="Project parameters">
      <h3>Project parameters</h3>
      <p><small>Values not set by you are assumed defaults for the building type. Saving regenerates every floor as a new version; clear a field to return to the default.</small></p>
      {errors.map((e) => <p key={e} role="alert" className={styles.error}>{e}</p>)}
      <table className={styles.table}>
        <tbody>
          {Object.entries(loaded).map(([k, p]) => (
            <tr key={k}>
              <th scope="row" style={{ textAlign: "left", fontWeight: 400 }}><label htmlFor={`param-${k}`}>{PARAM_LABEL[k] ?? k}</label></th>
              <td>
                {k === "roof_type" ? (
                  <select id={`param-${k}`} value={text[k] ?? ""} disabled={readOnly || busy} onChange={(e) => setText({ ...text, [k]: e.target.value })}>
                    {ROOF_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                ) : (
                  <input id={`param-${k}`} inputMode="decimal" value={text[k] ?? ""} disabled={readOnly || busy} onChange={(e) => setText({ ...text, [k]: e.target.value })} />
                )}
              </td>
              <td>[{SOURCE_LABEL[p.source]}]</td>
            </tr>
          ))}
        </tbody>
      </table>
      {readOnly ? <p>Only editors and the owner can change parameters.</p> : <button type="button" disabled={busy} onClick={save}>Save and regenerate</button>}
      {status && <p role="status">{status}…</p>}
      {saved !== null && <p role="status">Regenerated every floor as version {saved}. Open the viewer to see the new model.</p>}
      {issues.length > 0 && <IssueList issues={issues} />}
    </section>
  );
}
