# services/api (Python, uv, FastAPI)

Turns restricted DXF floor plans into a canonical building model with provenance, then 3D GLB. Engine in `src/api/engine/`: adapters, canonical, geometry2d, geometry3d, exporters.

## Commands
- Postgres (repo root): `docker compose up -d`; schema: `uv run alembic upgrade head`; legacy import: `uv run api import-projects`
- Tests: `uv run pytest -q` (API tests need compose Postgres; they use a throwaway DB)
- Dev server: `uv run uvicorn api.main:app --reload`

## Accounts (`src/api/auth.py`)
- Every `/api/v1` router except `/api/v1/auth/*` depends on `current_user` (401 without a session). `/health` is public. Ownership is enforced through the single helper `api/access.py` (`owned`/`can_access`): non-owner, NULL-owner and soft-deleted rows all give 404. Projects keep immutable `project_versions`; `uv run api import-projects --owner <email>` assigns legacy projects.
- Env: `GITHUB_CLIENT_ID/SECRET`, `GOOGLE_CLIENT_ID/SECRET` (provider off = 503), `WEB_BASE_URL`, `AUTH_COOKIE_SECURE`, `SESSION_SECRET`, `AUTH_RATE_LIMIT_PER_MIN`.
- Tests: `conftest.py` logs in every `TestClient` automatically; mark auth tests `@pytest.mark.anon`.

## Rules
- All parsing and geometry rules live here; the viewer never duplicates them.
- Geometry rules: `.claude/rules/geometry.md` (auto-loads for engine code).
