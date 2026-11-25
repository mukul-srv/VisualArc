# apps/web (Next.js + Three.js viewer)

Browser viewer for engine output. Never duplicates parsing or geometry rules (those live in `services/api/`).

## Commands
- Dev: `npm run dev` · Test: `npm test` · Typecheck: `npm run typecheck`
- Lint: `npm run lint` · Build: `npm run build`
- `npm test` includes `workflow.test.ts`, which spawns the real API: `DATABASE_URL` must point at a migrated scratch DB, never `visual_arc` (the test fails otherwise).
- Next.js has breaking changes: read `node_modules/next/dist/docs/` first (see AGENTS.md).

## Worktree tip
Fresh worktree: don't `npm ci` unless the lockfile differs from main. If `apps/web/package-lock.json` matches main, link main's deps (PowerShell, from repo root):
`New-Item -ItemType Junction -Path apps/web/node_modules -Target <main-repo>/apps/web/node_modules`
`next build` needs a real `npm ci` — Turbopack does not follow the junction.

## Plan editor
- Trace-assist: a floor made from an image (`TraceFloorForm`, Floors tab) opens in `PlanEditor` with an underlay (`UnderlayPanel`: opacity, hide, lock, two-point calibration, `lib/underlay.ts`); tracing tools stay off until the scale is saved. The picture is only a guide, nothing is detected.
- `PlanEditor` (project Floors tab, editor+) edits walls, doors/windows and room names; doors and windows are drawn by dragging along a wall (height/sill tool fields, empty = project default). All logic is pure in `lib/plan-edit.ts` (hit-test, snap, drag, op builders mirroring `engine/edits.py`, undo/redo, local preview); the preview only moves edited rectangles, the server re-derives everything on save (`saveEditsJob`) and a block saves nothing.
