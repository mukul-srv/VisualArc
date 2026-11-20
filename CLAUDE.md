# CLAUDE.md

Portfolio project: restricted DXF floor plans -> canonical building model (with provenance) -> 3D GLB -> browser viewer. Verification-first.

## Current milestone
MVP-0 technical proof: DXF -> inventory -> canonical JSON -> wall/floor mesh -> GLB -> minimal viewer. Local only.

## Layout
- `services/api/` Python (uv, FastAPI), package `src/api/`. Engine in `src/api/engine/`: adapters (format -> canonical), canonical (models), geometry2d, geometry3d, exporters. Route handlers hold no geometry logic.
- `apps/web/` Next.js + Three.js viewer. Never duplicates parsing/geometry rules.
- `fixtures/` input DXFs, expected outputs, `LICENCES.md` for every fixture.
- `docs/project/` the 9 spec docs. Read only the one relevant to a task.
- `docs/learning/` Obsidian learning notes. `docs/architecture/decisions/` ADRs.

## Commands
- API tests: `cd services/api && uv run pytest`
- API dev: `cd services/api && uv run uvicorn api.main:app --reload`
- Web dev: `cd apps/web && npm run dev` ; tests: `npm test`

## Conventions
- Canonical units: millimetres. Plan X/Y -> GLB X/-Z, Y-up (ADR-001).
- First DXF convention: walls = paired parallel lines on layer `A-WALL`; floor = closed LWPOLYLINE on `A-FLOR`; orthogonal walls only.
- Every important value carries provenance: source_extracted | user_provided | defaulted | inferred.

## Learn-as-you-build
- Small, testable vertical slices. No unrelated refactors or dependencies.
- Multi-file or algorithmic work: short plan before editing.
- After implementation: what changed, input->output flow, key assumptions, tests run, at most two concepts worth understanding.
- Deeper walkthroughs only for geometry, coordinates, data modelling, validation, provenance, security.
- Update docs/learning only for durable concepts/decisions; prefer updating existing notes.
- Never claim tests passed unless run. Never weaken tests to hide a bug.
- Preserve verified dimensions and provenance. Never silently invent measurements. Never hardcode fixture coordinates to pass a test.
