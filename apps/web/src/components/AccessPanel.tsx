"use client";

import { useCallback, useEffect, useState } from "react";
import { createLink, getAccess, grantAccess, removeAccess, revokeLink, type AccessInfo } from "../lib/projects";
import { viewerUrl } from "../lib/project";
import styles from "./dashboard.module.css";

type Role = "viewer" | "editor";

// Owner-only sharing panel: collaborators and pending invites (role change, remove) and the read-only link.
export function AccessPanel({ projectId }: { projectId: string }) {
  const [info, setInfo] = useState<AccessInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [busy, setBusy] = useState(false);

  const apply = useCallback((r: Awaited<ReturnType<typeof getAccess>>) => {
    if (r.ok) {
      const { ok: _ok, ...rest } = r;
      void _ok;
      setInfo(rest as unknown as AccessInfo);
      setError(null);
    } else setError(r.message);
  }, []);
  useEffect(() => {
    getAccess(projectId).then(apply);
  }, [projectId, apply]);

  async function act(call: () => ReturnType<typeof getAccess>, after?: () => void) {
    setBusy(true);
    const r = await call();
    if (!r.ok) setError(r.message);
    else {
      after?.();
      await getAccess(projectId).then(apply);
    }
    setBusy(false);
  }

  const link = info?.link_token ? `${window.location.origin}${viewerUrl(projectId, undefined, undefined, info.link_token)}` : null;
  const used = info ? info.collaborators.length + info.invites.length : 0;
  const rows = info ? [
    ...info.collaborators.map((c) => ({ email: c.email, label: `${c.display_name} <${c.email}>`, role: c.role })),
    ...info.invites.map((i) => ({ email: i.email, label: `${i.email} (invited, not registered yet)`, role: i.role })),
  ] : [];
  return (
    <section aria-label="Sharing">
      <h2>Sharing</h2>
      {error && <p role="alert" className={styles.error}>Error: {error}</p>}
      {info && (
        <>
          <p>{used} of {info.max_collaborators} collaborator slots used.</p>
          <ul>
            {rows.map((r) => (
              <li key={r.email} className={styles.row}>
                {r.label}
                <select aria-label={`Role for ${r.email}`} value={r.role} disabled={busy}
                  onChange={(e) => act(() => grantAccess(projectId, r.email, e.target.value as Role))}>
                  <option value="viewer">viewer</option>
                  <option value="editor">editor</option>
                </select>
                <button type="button" disabled={busy} onClick={() => act(() => removeAccess(projectId, r.email))}>Remove</button>
              </li>
            ))}
          </ul>
          <form className={styles.row} onSubmit={(e) => { e.preventDefault(); act(() => grantAccess(projectId, email.trim(), role), () => setEmail("")); }}>
            <label>Email <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
            </select>
            <button disabled={busy || !email.trim()}>Add</button>
          </form>
          <h3>Read-only link</h3>
          {link ? (
            <div className={styles.row}>
              <input readOnly aria-label="Share link" value={link} size={50} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" disabled={busy} onClick={() => act(() => revokeLink(projectId))}>Revoke link</button>
            </div>
          ) : (
            <button type="button" disabled={busy} onClick={() => act(() => createLink(projectId))}>Create read-only link</button>
          )}
        </>
      )}
    </section>
  );
}
