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

const HEX32 = /^[0-9a-f]{32}$/;
const existing = (t: ProjectTarget) => t.on && HEX32.test(t.target.trim());

/** A different project (or switching the option) clears the elevation, whose default depends on the
 *  project. Conventions loaded from an existing project are dropped (back to AIA) when leaving it;
 *  moving to another existing project loads that one's instead, so no reset is asked for then. */
export function changeTarget(prev: ProjectTarget, next: ProjectTarget): { proj: ProjectTarget; resetConventions: boolean } {
  const moved = prev.on !== next.on || prev.target.trim() !== next.target.trim();
  return { proj: moved ? { ...next, elevation: "" } : next, resetConventions: moved && existing(prev) && !existing(next) };
}
