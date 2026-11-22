# services/api (Python, uv, FastAPI)

Turns restricted DXF floor plans into a canonical building model with provenance, then 3D GLB. Engine in `src/api/engine/`: adapters, canonical, geometry2d, geometry3d, exporters.

## Commands
- Postgres (repo root): `docker compose up -d`; schema: `uv run alembic upgrade head`; legacy import: `uv run api import-projects`
- Tests: `uv run pytest -q` (API tests need compose Postgres; they use a throwaway DB)
- Dev server: `uv run uvicorn api.main:app --reload`

## Accounts (`src/api/auth.py`)
- Every `/api/v1` router except `/api/v1/auth/*` depends on `current_user` (401 without a session). `/health` is public. Ownership is enforced through the single helper `api/access.py` (`owned`/`can_access`, `need` = viewer/editor/owner, default owner): no access, NULL-owner and soft-deleted rows all give 404. Sharing (`sharing.py`, owner only): grants by email, pending invites (claimed only on OAuth login with a verified email, never on password register), cap `MAX_COLLABORATORS`, one revocable `?share=<token>` read-only link; read-only endpoints use the `Principal` dependency. Projects keep immutable `project_versions`; `uv run api import-projects --owner <email>` assigns legacy projects.
- Jobs (`jobs.py`): `POST /api/v1/jobs/generations` and `/jobs/projects/{pid}/floors` return 202 `{job_id}`; one in-process worker thread runs them, `GET /jobs/{id}` is polled (stage queued/parsing/building-model/exporting/done, progress, error, result). Same access rules as the sync endpoints; `recover_jobs()` at startup fails jobs a dead process left running. Tests stub `jobs.submit` and call `jobs.execute`.
- Env: `GITHUB_CLIENT_ID/SECRET`, `GOOGLE_CLIENT_ID/SECRET` (provider off = 503), `WEB_BASE_URL`, `AUTH_COOKIE_SECURE`, `SESSION_SECRET`, `AUTH_RATE_LIMIT_PER_MIN`.
- Tests: `conftest.py` logs in every `TestClient` automatically; mark auth tests `@pytest.mark.anon`.

## Rules
- All parsing and geometry rules live here; the viewer never duplicates them.
- Geometry rules: `.claude/rules/geometry.md` (auto-loads for engine code).
