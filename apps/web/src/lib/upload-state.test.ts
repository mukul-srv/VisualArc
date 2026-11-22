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
