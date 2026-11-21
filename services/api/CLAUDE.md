# services/api (Python, uv, FastAPI)

Turns restricted DXF floor plans into a canonical building model with provenance, then 3D GLB. Engine in `src/api/engine/`: adapters, canonical, geometry2d, geometry3d, exporters.

## Commands
- Tests: `uv run pytest -q`
- Dev server: `uv run uvicorn api.main:app --reload`

## Rules
- All parsing and geometry rules live here; the viewer never duplicates them.
- Canonical units are millimetres. Plan X/Y -> GLB X/-Z, Y-up (ADR-001).
- Thresholds and tolerances live in `engine/settings.py` (ADR-003). No magic numbers.
- Preserve provenance: `source_extracted`, `user_provided`, `defaulted`, `inferred`.
- Initial DXF convention: paired parallel lines on `A-WALL`; closed LWPOLYLINE on `A-FLOR`; orthogonal walls only (Document 08 §3a).
- Numerical resource limits come from benchmarks, not assumptions.
