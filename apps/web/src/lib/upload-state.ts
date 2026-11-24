import type { FormValues } from "./params";
import type { ProjectTarget } from "../components/UploadForm";

// What the upload page keeps and clears when the file or the project target changes. Everything
// read from or typed for one file (heights, units, floor name and elevation, split rows) is cleared
// on a new file; a project opened with ?project=<id> stays the target; conventions come from the
// project (or the AIA default), never from the previous file.
export const EMPTY_FORM: FormValues = {
  buildingType: "residential",
  wallHeight: "",
  ceilingHeight: "",
  units: "",
  doorHeight: "",
  windowHeight: "",
  windowSill: "",
};
export const NO_TARGET: ProjectTarget = { on: false, target: "", floorName: "", elevation: "" };

export function resetForNewFile(proj: ProjectTarget, locked: boolean) {
  return {
    form: EMPTY_FORM,
    projectName: "",
    proj: locked ? { ...NO_TARGET, on: true, target: proj.target } : NO_TARGET,
  };
}

/** Where the person is in the upload flow, in plain words (shown as one line above the form). */
export function uploadStep(hasFile: boolean, working: boolean, addingToProject: boolean): string {
  // working without a checked file = still reading the upload; with one = building the model
  if (working) return hasFile ? "Step 3 of 3: building the 3D model. You will land in the viewer when it is ready." : "Step 1 of 3: reading your file.";
  if (!hasFile) return `Step 1 of 3: choose your DXF floor plan${addingToProject ? " for the new floor" : ""}.`;
  return "Step 2 of 3: check the notes below, then press Generate. The defaults are fine to start with.";
}

/** Remount key of the upload page: one per query string, so a different project target never
 *  inherits the previous file name, form or split rows. */
export const uploadKey = (search: string) => `new:${search}`;

/** A page restored from the browser's back/forward cache keeps its old DOM, including the file
 *  input's file name; the flow must start over then. */
export const restoredFromCache = (e: { persisted?: boolean }) => e.persisted === true;

/** After a new project was created for this upload, the form's target is that project: a retry (for
 *  instance after a blocking issue was fixed) adds the floor to it instead of creating a second,
 *  empty project of the same name from the same file. */
export const targetAfterCreate = (proj: ProjectTarget, projectId: string): ProjectTarget => ({ ...proj, target: projectId });

const HEX32 = /^[0-9a-f]{32}$/;
const existing = (t: ProjectTarget) => t.on && HEX32.test(t.target.trim());

/** A different project (or switching the option) clears the elevation, whose default depends on the
 *  project. Conventions loaded from an existing project are dropped (back to AIA) when leaving it;
 *  moving to another existing project loads that one's instead, so no reset is asked for then. */
export function changeTarget(prev: ProjectTarget, next: ProjectTarget): { proj: ProjectTarget; resetConventions: boolean } {
  const moved = prev.on !== next.on || prev.target.trim() !== next.target.trim();
  return { proj: moved ? { ...next, elevation: "" } : next, resetConventions: moved && existing(prev) && !existing(next) };
}

/** Everything a review was read from; Accept must save exactly this, so any change makes the review stale. */
export const reviewKey = (inputs: unknown): string => JSON.stringify(inputs);
export const reviewStale = (saved: string | null, inputs: unknown): boolean => saved !== null && saved !== reviewKey(inputs);
