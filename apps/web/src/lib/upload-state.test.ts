import { expect, test } from "vitest";
import { changeTarget, EMPTY_FORM, NO_TARGET, resetForNewFile } from "./upload-state";

const pid = "a".repeat(32);
const typed = { on: true, target: pid, floorName: "Ground", elevation: "3000" };

test("a new file clears everything typed for the previous one and the project option", () => {
  const r = resetForNewFile(typed, false);
  expect(r.form).toEqual(EMPTY_FORM);
  expect(r.projectName).toBe("");
  expect(r.proj).toEqual(NO_TARGET); // unticked, no stale name or elevation
});

test("a project opened with ?project= stays the target but floor name and elevation reset", () => {
  expect(resetForNewFile(typed, true).proj).toEqual({ on: true, target: pid, floorName: "", elevation: "" });
});

test("changing the target clears the elevation (its default depends on the project) and keeps the floor name", () => {
  const r = changeTarget(typed, { ...typed, target: "b".repeat(32) });
  expect(r.proj).toEqual({ ...typed, target: "b".repeat(32), elevation: "" });
  expect(r.resetConventions).toBe(false); // the other project's conventions are loaded instead
});

test("leaving an existing project drops its conventions; typing a new name does not trigger a reset each key", () => {
  expect(changeTarget(typed, { ...typed, target: "New house" }).resetConventions).toBe(true);
  expect(changeTarget(typed, { ...typed, on: false }).resetConventions).toBe(true);
  const typing = { on: true, target: "Ne", floorName: "", elevation: "" };
  expect(changeTarget(typing, { ...typing, target: "New" })).toEqual({ proj: { ...typing, target: "New", elevation: "" }, resetConventions: false });
});

test("editing other fields changes nothing else", () => {
  const r = changeTarget(typed, { ...typed, floorName: "First", elevation: "6000" });
  expect(r.proj.elevation).toBe("6000");
  expect(r.resetConventions).toBe(false);
});

import { restoredFromCache, uploadKey } from "./upload-state";

test("the upload page is keyed by its query string, and a bfcache restore starts it over", () => {
  expect(uploadKey("")).not.toBe(uploadKey("project=abc"));
  expect(uploadKey("project=abc")).not.toBe(uploadKey("project=def"));
  expect(uploadKey("project=abc")).toBe(uploadKey("project=abc"));
  expect(restoredFromCache({ persisted: true })).toBe(true);
  expect(restoredFromCache({ persisted: false })).toBe(false);
  expect(restoredFromCache({})).toBe(false);
});


import { uploadStep } from "./upload-state";

test("the step line says reading while the upload is checked, building only while generating", () => {
  expect(uploadStep(false, false, false)).toMatch(/^Step 1 of 3: choose/);
  expect(uploadStep(false, true, false)).toMatch(/^Step 1 of 3: reading/); // uploading and preflight
  expect(uploadStep(true, false, false)).toMatch(/^Step 2 of 3/);
  expect(uploadStep(true, true, false)).toMatch(/^Step 3 of 3: building/);
  expect(uploadStep(false, false, true)).toContain("for the new floor");
});

import { targetAfterCreate } from "./upload-state";

test("once a project was created for the upload, a retry joins it instead of creating a second one", () => {
  const typed = { on: true, target: "House", floorName: "Ground", elevation: "" };
  const after = targetAfterCreate(typed, "a".repeat(32));
  expect(after.target).toBe("a".repeat(32)); // an id now, so the form adds a floor instead of creating a project
  expect(after.floorName).toBe("Ground");
});
