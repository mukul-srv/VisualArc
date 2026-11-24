"use client";

import Link from "next/link";
import { useState } from "react";
import { sortFloors, viewerUrl, type Floor, type Role } from "../lib/project";
import { HELP } from "../lib/help";
import { MoreMenu } from "./MoreMenu";
import { HelpLine, useHelp } from "./HelpLine";
import styles from "./dashboard.module.css";

export type TabId = "floors" | "parameters" | "versions" | "sharing";

/** Which actions a role gets: viewers read, editors change content, only the owner shares/deletes. */
export const can = (role: Role) => ({
  edit: role !== "viewer",
  manage: role === "owner",
});

// Layer conventions are not a tab: they only matter for floors you add, so they sit under Floors.
export const tabsFor = (role: Role): { id: TabId; label: string; help: string }[] => [
  { id: "floors", label: "Floors", help: "The floors of this project and their 3D models." },
  { id: "parameters", label: "Parameters", help: HELP.parameters },
  { id: "versions", label: "Versions", help: HELP.versions },
  ...(can(role).manage ? [{ id: "sharing" as const, label: "Sharing", help: HELP.link }] : []),
];

export function ProjectToolbar(p: {
  id: string;
  role: Role;
  floors: Floor[];
  busy?: boolean;
  onShare: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const { edit, manage } = can(p.role);
  const first = sortFloors(p.floors)[0];
  return (
    <div role="toolbar" aria-label="Project actions" className={styles.row}>
      {first ? (
        <a href={viewerUrl(p.id, first.id)}>Open in viewer</a>
      ) : (
        <span title="Add a floor first" aria-disabled="true">Open in viewer (no floors yet)</span>
      )}
      {edit && <Link href={`/new?project=${p.id}`}>Add floor</Link>}
      {edit && (
        <MoreMenu title={HELP.more}>
          {manage && <button type="button" onClick={p.onShare}>Share</button>}
          <button type="button" disabled={p.busy} onClick={p.onRename}>Rename</button>
          {manage && <button type="button" disabled={p.busy} onClick={p.onDelete}>Delete</button>}
        </MoreMenu>
      )}
    </div>
  );
}

export function ProjectTabs({ role, tab, onSelect }: { role: Role; tab: TabId; onSelect: (t: TabId) => void }) {
  const { help, about } = useHelp();
  return (
    <>
      <div role="tablist" aria-label="Project sections" className={styles.row}>
        {tabsFor(role).map((t) => (
          <button key={t.id} role="tab" type="button" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
            style={{ fontWeight: tab === t.id ? 700 : 400 }} onClick={() => onSelect(t.id)} {...about(t.help)}>
            {t.label}
          </button>
        ))}
      </div>
      <HelpLine text={help} />
    </>
  );
}

/** Floors with per-floor actions (editor and owner): rename and remove, each a new version. */
export function FloorList(p: {
  projectId: string;
  floors: Floor[];
  role: Role;
  busy?: boolean;
  onRename: (floorId: string, name: string) => void;
  onRemove: (floorId: string) => void;
  onEditPlan?: (floorId: string) => void; // editors and the owner: opens the 2D plan editor
}) {
  const { edit } = can(p.role);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  if (p.floors.length === 0)
    return <p>No floors yet.{edit && <> <Link href={`/new?project=${p.projectId}`}>Add the first floor</Link>.</>}</p>;
  return (
    <ul aria-label="Floors">
      {sortFloors(p.floors).map((f) => (
        <li key={f.id} className={styles.row}>
          {renaming?.id === f.id ? (
            <form className={styles.row} onSubmit={(e) => { e.preventDefault(); p.onRename(f.id, renaming.name.trim()); setRenaming(null); }}>
              <input aria-label={`New name for ${f.name}`} value={renaming.name} maxLength={100} onChange={(e) => setRenaming({ id: f.id, name: e.target.value })} />
              <button disabled={p.busy || !renaming.name.trim() || renaming.name.trim() === f.name}>Save</button>
              <button type="button" onClick={() => setRenaming(null)}>Cancel</button>
            </form>
          ) : (
            <>
              <span>{f.name} at {f.elevation.value} mm</span>
              <a href={viewerUrl(p.projectId, f.id)}>Open in viewer</a>
              {edit && p.onEditPlan && <button type="button" disabled={p.busy} onClick={() => p.onEditPlan!(f.id)}>Edit plan</button>}
              {edit && (
                <MoreMenu title={HELP.more}>
                  <button type="button" disabled={p.busy} onClick={() => setRenaming({ id: f.id, name: f.name })}>Rename</button>
                  {removing !== f.id && <button type="button" disabled={p.busy} onClick={() => setRemoving(f.id)}>Remove</button>}
                  {removing === f.id && (
                    <span role="alertdialog" aria-label={`Confirm remove ${f.name}`}>
                      Remove {f.name}? Older versions keep it; restore brings it back.{" "}
                      <button type="button" disabled={p.busy} onClick={() => { p.onRemove(f.id); setRemoving(null); }}>Confirm remove</button>{" "}
                      <button type="button" onClick={() => setRemoving(null)}>Cancel</button>
                    </span>
                  )}
                </MoreMenu>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
