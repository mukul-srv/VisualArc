# Architectural Plan-to-3D Reconstruction and Verification Engine

Turns a restricted, documented subset of 2D DXF floor plans into measurable 3D geometry
(GLB) and a verification report, keeping every dimension traceable to its source drawing
entity or user input. Nothing is guessed: unsupported or ambiguous input is reported, and
every value carries its provenance (`source_extracted`, `user_provided`, `defaulted`,
`inferred`).

Pipeline: **DXF -> inventory/interpretation -> canonical model (JSON, with provenance)
-> 3D geometry -> GLB + metadata + report -> browser viewer**.

Status: Phase 0 complete (local workflow: CLI, API, web upload, viewer, multi-floor
projects). Not deployed. Limits below are provisional.

## Features
- **Issues:** each issue links to its source drawing entities in the issue list.
- **Viewer:** orbit, orthographic plan view, first-person walk mode, point-to-point measure
  tool with snapping, metadata panel.
- **Walls:** role `exterior` or `interior` from layers `A-WALL-EXTR` / `A-WALL-INTR`, else
  inferred (provenance kept).
- **Ceiling:** ceiling height input and ceiling element (shown in walk mode).
- **Materials:** per element and per wall role.
- **Projects:** several floors per project with a floor selector (`/viewer?project=<id>`).
- **Multi-floor DXF:** a consolidated DXF is split into floors; each floor gets a name,
  elevation and offset you confirm before generation (blocks until confirmed).
- **Input validation:** non-finite numbers are rejected with HTTP 422.

## Requirements
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 24 + npm (the web tests also call `uv`, so install both)

## Setup and tests
```bash
docker compose up -d                             # Postgres (API tests need it)
docker compose up -d                             # Postgres (API tests need it)
cd services/api && uv sync && uv run pytest      # API + engine tests
cd apps/web && npm ci && npm test                # web tests (builds fixtures via the API CLI, starts a real API)
cd apps/web && npm run lint && npm run build     # type-check, lint, production build
```

## Supported drawing convention (summary)
A restricted convention; everything else is listed as an issue.
- **Units:** from the DXF `$INSUNITS` header (mm, cm, m, in, ft). If missing, pass `--units`;
  a header/`--units` conflict or an unsupported unit blocks generation.
- **Walls:** layer `A-WALL`, straight `LINE`s or straight `LWPOLYLINE`s. A wall is two
  parallel horizontal/vertical face lines 50-600 mm apart; the overlap is its length.
  Corners/T-junctions are filled automatically. Duplicate or ambiguous lines block.
- **Floors:** layer `A-FLOR`, one closed straight `LWPOLYLINE` per room.
- **Openings:** a gap in the wall lines plus a closed rectangular `LWPOLYLINE` marker
  exactly filling it, on `A-DOOR` (door) or `A-GLAZ` (window). Heights come from flags or
  provisional defaults (door 2100 mm, sill 0; window 1200 mm, sill 900), always flagged.
- **Wall height** is never in the DXF: supply `--wall-height` (mm). Layer names are
  case-insensitive. One plan per generation; a DXF with several floors is split (see Features).

## Command line
```bash
cd services/api
uv run api inspect  ../../fixtures/input/fixture_a.dxf                       # DXF inventory (JSON)
uv run api interpret ../../fixtures/input/fixture_a.dxf --wall-height 3000   # canonical model JSON
uv run api build ../../fixtures/input/fixture_openings.dxf --wall-height 3000 --out ../../out
```
`build` writes `<stem>.canonical.json`, `<stem>.report.md` (always, even when blocked) and,
if nothing blocks, `<stem>.glb` and `<stem>.meta.json`.
Options: `--units {mm,cm,m,in,ft}`, `--door-height`, `--window-height`, `--window-sill`
(mm), `--max-mb`, and for `build` `--expected <canonical.json>` (adds an
expected-vs-generated table to the report).
Exit codes: `0` ok, `1` blocking issues, `2` usage error, `3` rejected input (not a DXF,
corrupt, or over a limit).

## Browser workflow
```bash
# terminal 0 (once): docker compose up -d && cd services/api && uv run alembic upgrade head
# terminal 0 (once): docker compose up -d && cd services/api && uv run alembic upgrade head
# terminal 1
cd services/api && uv run uvicorn api.main:app --reload     # http://127.0.0.1:8000
# terminal 2
cd apps/web && npm run dev                                  # http://localhost:3000
```
Open http://localhost:3000, choose a DXF, review the preflight issues (blocking vs
warnings), enter wall height (and units if the DXF has none), then Generate. The viewer
opens at `/viewer?generation=<id>`: orbit with the mouse, **click** a wall, junction, floor
or opening to see its dimensions, provenance and source entities.
Press **Walk** for first-person mode: WASD/arrows to move, drag to look, Esc to exit. You
collide with the real wall meshes, so doors (sill 0) can be walked through and windows
(sill 0.9 m) cannot.

To view a locally built GLB instead:
```bash
cd services/api
uv run api build ../../fixtures/input/fixture_b.dxf --wall-height 3000 --out ../../apps/web/public/models
# then open http://localhost:3000/viewer?model=fixture_b   (default model: fixture_a)
```
`apps/web/public/models/` is git-ignored. The stem may contain only `A-Z a-z 0-9 _ -`.

### Accounts and login
All `/api/v1` endpoints except `/api/v1/auth/*` need a session cookie (`POST /api/v1/auth/register`
or `/login`); `/health` is public. The web app proxies `/api/*` to the API (Next rewrite,
target `NEXT_PUBLIC_API_URL`) so the cookie is first-party. Pages: `/login`, `/register`, `/profile`.
Run `uv run alembic upgrade head` after pulling (migration 0002).

OAuth is optional. Register an app and export the credentials before starting the API:
- GitHub: Settings > Developer settings > OAuth Apps > New. Callback URL
  `http://localhost:3000/api/v1/auth/oauth/github/callback`. Set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.
- Google: Cloud Console > APIs & Services > Credentials > OAuth client ID (Web). Authorised redirect URI
  `http://localhost:3000/api/v1/auth/oauth/google/callback`. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
A provider without credentials returns 503 and its login button is hidden. Other settings:
`WEB_BASE_URL` (default `http://localhost:3000`), `AUTH_COOKIE_SECURE=true` behind HTTPS,
`SESSION_SECRET` (set when running more than one worker), `AUTH_RATE_LIMIT_PER_MIN` (default 10).

Configuration: `API_DATA_DIR` (API storage, default a temp folder), `API_CORS_ORIGINS`
(comma-separated, default the local web origins), `NEXT_PUBLIC_API_URL` (web, default
`http://127.0.0.1:8000`; now the target of the `/api/*` rewrite).

## API
| Method and path | Purpose |
|---|---|
| `GET /health` | liveness |
| `POST /api/v1/uploads` | body = raw DXF (`application/octet-stream`); returns `upload_id`, inventory, issues, `needs` (`wall_height`, `units`). 413 over size, 422 invalid or over a limit |
| `POST /api/v1/uploads/{id}/split` | confirm floors of a consolidated DXF; 201 with one project and one generation per floor, 409 if any floor blocks |
| `POST /api/v1/projects`, `POST /api/v1/projects/{pid}/floors`, `GET /api/v1/projects/{pid}` | multi-floor projects |
| `POST /api/v1/generations` | JSON `{upload_id, wall_height, units?, door_height?, window_height?, window_sill?}`; 201 with artifact URLs, 409 with structured issues if blocked |
| `GET /api/v1/generations/{id}/artifacts/{glb,meta,canonical,report}` | download artifacts |
| `GET /api/v1/projects/{pid}/export/{obj,ifc}`, `GET /api/v1/generations/{id}/export/{obj,ifc}` | OBJ (metres, Y up, as the GLB) or IFC4 (mm; typed elements per storey, provenance property sets; unmappable elements become proxies with a recorded issue); viewer role or share link |
| `POST /api/v1/uploads` (IFC body), `POST /api/v1/uploads/{id}/ifc` | an IFC upload is detected by its header; the second call makes a project with a floor per storey (unsupported entities are reported as issues) |

## Limits (provisional)
Enforced before interpretation (CLI exit 3, API 422): **600** wall-layer segments,
**120** opening markers, **5,000** total entities, **5 MiB** file size. They come from a
benchmark on synthetic, regular fixtures only (not representative drawings, not a hosted
server): interpretation time grows roughly with the cube of the wall count, so larger
drawings are rejected rather than left to run for minutes. Evidence, method and known
performance debt: `benchmarks/t21-benchmark-report.md`. Re-run with
`cd services/api && uv run python ../../scripts/benchmark.py` (runs above the limits on purpose).

## Known limitations
- Orthogonal walls only; arcs, blocks, non-Z extrusion and sloped lines are reported and
  skipped (a model can generate with such walls missing: check the warnings).
- No drafting tolerance: lines that are off by a fraction of a millimetre are not paired.
- Floor detection in one DXF is heuristic (layer prefix, else spatial gap). Files without a
  `$INSUNITS` header show no split table until units are given; generation then blocks.
- API storage is local disk with no expiry; the API processes requests synchronously (no
  job timeout or worker process), so it is for local use, not public hosting.
- Walk mode probes at fixed heights: a window with a sill below 0.3 m and a head above 1.6 m
  behaves like a door; no stairs or multi-floor navigation.
- The viewer is validated by manual inspection and by loading the served GLB in tests; there
  is no automated browser/WebGL test.

## Fixtures
Self-generated, see `fixtures/LICENCES.md`. `fixture_a` (two rooms), `fixture_b` (L-shaped
room), `fixture_c` (Fixture A drawn with closed polylines and lower-case layers),
`fixture_d` (nine copies of the openings fixture, for scale), `fixture_openings` (three
rooms, seven doors/windows). Regenerate with `scripts/make_fixture_*.py`.

## Repository layout
- `services/api/` Python (FastAPI, ezdxf, shapely, trimesh): `src/api/engine/` (adapters, canonical model, geometry2d, geometry3d, exporters), `cli.py`, API modules, tests.
- `apps/web/` Next.js + Three.js viewer and upload UI (no parsing or geometry rules).
- `fixtures/` input DXFs and expected outputs; `scripts/` fixture generators and the benchmark; `benchmarks/` benchmark report and raw results.
