import { API_BASE, send } from "./api";
import type { Floor } from "./project";

// Trace-assist underlay: a picture under an empty floor, to trace over by hand. Nothing is detected.
// Image pixel (px, py) has its origin top-left, y down; plan mm has y up. With m = mm per pixel,
// pixel (px, py) is plan (px * m, (height_px - py) * m): the picture's bottom-left corner is the plan origin.
type Fetch = typeof fetch;

export type Calibration = { p1: [number, number]; p2: [number, number]; distance_mm: number; mm_per_px: number; source: "user_provided" };
export type Underlay = { url: string; width_px: number; height_px: number; calibration: Calibration | null };

export const MIN_CALIBRATION_PX = 10; // mirrors the API: closer points are mostly click noise

/** mm per pixel; an uncalibrated picture is shown at 1 px = 1 mm, only so its two calibration points can be picked. */
export const mmPerPx = (u: Underlay): number => u.calibration?.mm_per_px ?? 1;

export const pxToPlan = (u: Underlay, px: number, py: number): [number, number] => [px * mmPerPx(u), (u.height_px - py) * mmPerPx(u)];
export const planToPx = (u: Underlay, x: number, y: number): [number, number] => [x / mmPerPx(u), u.height_px - y / mmPerPx(u)];

/** The picture's rectangle in plan mm. */
export function imageRect(u: Underlay): { x0: number; y0: number; x1: number; y1: number } {
  const m = mmPerPx(u);
  return { x0: 0, y0: 0, x1: u.width_px * m, y1: u.height_px * m };
}

/** The two-point scale: mm per pixel from two picked pixels and the real distance between them (mm). */
export function calibrationScale(p1: [number, number], p2: [number, number], distanceMm: number): { ok: true; mmPerPx: number } | { ok: false; error: string } {
  const px = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  if (!(px >= MIN_CALIBRATION_PX)) return { ok: false, error: `The two points are ${px.toFixed(1)} px apart; pick points at least ${MIN_CALIBRATION_PX} px apart.` };
  if (!(distanceMm > 0 && Number.isFinite(distanceMm))) return { ok: false, error: "Enter the real distance between the points in mm (above 0)." };
  return { ok: true, mmPerPx: distanceMm / px };
}

export const putCalibration = (pid: string, floorId: string, p1: [number, number], p2: [number, number], distanceMm: number, f: Fetch = fetch) =>
  send<{ calibration: Calibration }>(() =>
    f(`${API_BASE}/api/v1/projects/${pid}/floors/${floorId}/underlay/calibration`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ p1, p2, distance_mm: distanceMm }),
    }),
  );

/** A new empty floor with the image (PNG, JPEG or a PDF's first page) as its underlay. */
export const createTraceFloor = (file: Blob & { name?: string }, q: { projectId?: string; projectName?: string; floorName: string; elevation?: number }, f: Fetch = fetch) => {
  const p = new URLSearchParams({ floor_name: q.floorName });
  if (q.projectId) p.set("project_id", q.projectId);
  if (q.projectName) p.set("project_name", q.projectName);
  if (q.elevation !== undefined) p.set("elevation", String(q.elevation));
  if (file.name) p.set("filename", file.name);
  return send<{ project_id: string; floor: Floor; issues: unknown[] }>(() =>
    f(`${API_BASE}/api/v1/trace/floors?${p}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/octet-stream" }, body: file }),
  );
};
