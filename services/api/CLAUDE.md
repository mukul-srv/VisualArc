# services/api (Python, uv, FastAPI)

Turns restricted DXF floor plans into a canonical building model with provenance, then 3D GLB. Engine in `src/api/engine/`: adapters, canonical, geometry2d, geometry3d, exporters.

## Commands
- Postgres (repo root): `docker compose up -d`; schema: `uv run alembic upgrade head`; legacy import: `uv run api import-projects`
- Tests: `uv run pytest -q` (API tests need compose Postgres; they use a throwaway DB)
- Dev server: `uv run uvicorn api.main:app --reload`

## Rules
- All parsing and geometry rules live here; the viewer never duplicates them.
- Geometry rules: `.claude/rules/geometry.md` (auto-loads for engine code).
