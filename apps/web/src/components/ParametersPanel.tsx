"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { changeParametersJob, STAGE_LABEL } from "../lib/jobs";
import { diffParameters, legacyNotice, PARAM_LABEL, ROOF_TYPES } from "../lib/parameters";
import { HELP, PARAM_HELP } from "../lib/help";
import { Hint } from "./Hint";
import { getParameters, type ProjectParam } from "../lib/projects";
import type { Issue } from "../lib/api";
import { IssueList } from "./IssueList";
import styles from "./dashboard.module.css";

const ESSENTIAL = ["wall_height", "ceiling_height", "roof_type", "roof_pitch"]; // what most people change
const OTHER = (loaded: Record<string, ProjectParam>) => Object.keys(loaded).filter((k) => !ESSENTIAL.includes(k));

function ParamTable({ names, loaded, text, setText, disabled }: {
  names: string[];
  loaded: Record<string, ProjectParam>;
  text: Record<string, string>;
  setText: (t: Record<string, string>) => void;
  disabled: boolean;
}) {
  return (
    <table className={styles.table}>
      <tbody>
        {names.filter((k) => loaded[k]).map((k) => (
          <tr key={k}>
            <th scope="row" style={{ textAlign: "left", fontWeight: 400 }}>
              <label htmlFor={`param-${k}`}>{PARAM_LABEL[k] ?? k}</label>
              <Hint text={PARAM_HELP[k] ?? ""} />
            </th>
            <td>
              {k === "roof_type" ? (
                <select id={`param-${k}`} value={text[k] ?? ""} disabled={disabled} onChange={(e) => setText({ ...text, [k]: e.target.value })}>
                  {ROOF_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              ) : (
                <input id={`param-${k}`} inputMode="decimal" value={text[k] ?? ""} disabled={disabled} onChange={(e) => setText({ ...text, [k]: e.target.value })} />
              )}
            </td>
            <td title={HELP.provenance}>{loaded[k].source === "user_provided" ? "set by you" : "default"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

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
  const [legacy, setLegacy] = useState<string[]>([]); // floors that predate stored settings: cannot be rebuilt

  const load = useCallback(async () => {
    const r = await getParameters(projectId);
    if (!r.ok) return setErrors([r.message]);
    const params: Record<string, ProjectParam> = {};
    for (const [k, v] of Object.entries(r)) if (k !== "ok" && !k.startsWith("_")) params[k] = v as ProjectParam;
    setLegacy(((r as Record<string, unknown>)._legacy_floors as string[] | undefined) ?? []);
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

  const notice = legacyNotice(legacy, projectId);
  if (!loaded) return errors.length ? <p role="alert" className={styles.error}>{errors[0]}</p> : <p role="status">Loading…</p>;
  return (
    <section aria-label="Project parameters">
      <h3>Project parameters</h3>
      {notice && (
        <p role="alert" className={styles.error}>
          {notice.text} <Link href={notice.href}>{notice.action}</Link>
        </p>
      )}
      <p><small>Values you have not set are defaults for the building type. Change a value and save: every floor is rebuilt as a new version. Clear a field to go back to the default.</small></p>
      {errors.map((e) => <p key={e} role="alert" className={styles.error}>{e}</p>)}
      <ParamTable names={ESSENTIAL} loaded={loaded} text={text} setText={setText} disabled={readOnly || busy} />
      {OTHER(loaded).length > 0 && (
        <details>
          <summary title="Slab, stairs, windows, lintel and railings">More parameters ({OTHER(loaded).length})</summary>
          <ParamTable names={OTHER(loaded)} loaded={loaded} text={text} setText={setText} disabled={readOnly || busy} />
        </details>
      )}
      {readOnly ? <p>Only editors and the owner can change parameters.</p> : <button type="button" disabled={busy || legacy.length > 0} title={legacy.length > 0 ? "Add the older floors again first (see the note above)" : undefined} onClick={save}>Save and regenerate</button>}
      {status && <p role="status">{status}…</p>}
      {saved !== null && <p role="status">Regenerated every floor as version {saved}. Open the viewer to see the new model.</p>}
      {issues.length > 0 && <IssueList issues={issues} />}
    </section>
  );
}
