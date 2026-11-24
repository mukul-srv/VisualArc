# services/api (Python, uv, FastAPI)

Turns restricted DXF floor plans into a canonical building model with provenance, then 3D GLB. Engine in `src/api/engine/`: adapters, canonical, geometry2d, geometry3d, exporters.

## Commands
- Postgres (repo root): `docker compose up -d`; schema: `uv run alembic upgrade head`; legacy import: `uv run api import-projects`
- Tests: `uv run pytest -q` (API tests need compose Postgres; they use a throwaway DB)
- Dev server: `uv run uvicorn api.main:app --reload`

## Accounts (`src/api/auth.py`)
- Every `/api/v1` router except `/api/v1/auth/*` depends on `current_user` (401 without a session). `/health` is public. Ownership is enforced through the single helper `api/access.py` (`owned`/`can_access`, `need` = viewer/editor/owner, default owner): no access, NULL-owner and soft-deleted rows all give 404. Sharing (`sharing.py`, owner only): grants by email, pending invites (claimed only on OAuth login with a verified email, never on password register), cap `MAX_COLLABORATORS`, one revocable `?share=<token>` read-only link; read-only endpoints use the `Principal` dependency. Projects keep immutable `project_versions`; `uv run api import-projects --owner <email>` assigns legacy projects.
- Edits: `PUT /jobs/projects/{pid}/floors/{fid}/edits` (editor+, job kind `edits`) stores the floor's ordered `edits` (`engine/edits.py`: ops carry a target snapshot, not an id) in the manifest, replays only that floor via `read_dxf(edits=)` and makes one version; `edit_target_missing` is a warning, a blocking result changes nothing; `_replay` keeps edits through parameter changes.
- Draft: job kind `draft` (`POST /jobs/uploads/{id}/draft`, upload owner) runs `read_project` per floor and stores nothing; result per floor = issues, stats, plan overlay (`plan_overlay.overlay_of`); accept = the normal generate/split calls.
- Jobs (`jobs.py`): `POST /api/v1/jobs/generations` and `/jobs/projects/{pid}/floors` return 202 `{job_id}`; one in-process worker thread runs them, `GET /jobs/{id}` is polled (stage queued/parsing/building-model/exporting/done, progress, error, result). Same access rules as the sync endpoints; `recover_jobs()` at startup fails jobs a dead process left running. Tests stub `jobs.submit` and call `jobs.execute`.
- Conventions (`engine/conventions.py`, `layer_conventions.py`): layer names are per-project config, not constants: preset (`aia` = the `Settings` defaults, `iso13567` minimal subset, `custom`) plus a layer->role mapping resolved into `Settings`. Saved per project (`project_conventions`, editor/owner write, viewer read); a floor request without `conventions` uses the project's. Unmapped layers stay `unmapped_layer` issues; `ignore` gives `layer_ignored_by_user`.
- Floors after generation (`projects.py`): `PATCH/DELETE /projects/{pid}/floors/{fid}` rename/remove (editor+, each a new version; geometry editing is Section D); `POST /projects/from-generation` turns a standalone model into a project. New floor ids are max index + 1.
- Building (`building.py`): `GET /projects/{pid}/building` (viewer) = floors by elevation with plan offsets, stair pairings, issues, stats; `PUT /floors/{fid}/offset`, `PUT /building/pairings` (confirm/re-pair), `POST /building/pairings/unpair` (editor+, each a version). Offsets and `pairings` live in the manifest (snapshotted); `auto` pairs are recomputed on read. Alignment and stair issues are warnings, nothing is auto-shifted.
- Env: `GITHUB_CLIENT_ID/SECRET`, `GOOGLE_CLIENT_ID/SECRET` (provider off = 503), `WEB_BASE_URL`, `AUTH_COOKIE_SECURE`, `SESSION_SECRET`, `AUTH_RATE_LIMIT_PER_MIN`.
- Tests: `conftest.py` logs in every `TestClient` automatically; mark auth tests `@pytest.mark.anon`.

## Rules
- All parsing and geometry rules live here; the viewer never duplicates them.
- Geometry rules: `.claude/rules/geometry.md` (auto-loads for engine code).
