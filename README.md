# Architectural Plan-to-3D Reconstruction and Verification Engine

Turns a restricted, documented subset of 2D DXF floor plans into measurable 3D geometry, keeping every dimension traceable to its source drawing entity or user input.

Status: Phase 0 (skeleton). See `docs/project/` for the PRD, scope, architecture and roadmap.

## Requirements
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 24 + npm

## Run
```bash
# API
cd services/api
uv sync
uv run pytest
uv run uvicorn api.main:app --reload   # http://127.0.0.1:8000/health

# Web
cd apps/web
npm install
npm test
npm run dev                            # http://localhost:3000
```

## View a model
```bash
# 1. Build (writes <stem>.canonical.json, <stem>.glb, <stem>.meta.json, <stem>.report.md (add --expected <canonical.json> for expected-vs-generated); stem = DXF filename)
cd services/api
uv run api build ../../fixtures/input/fixture_b.dxf --wall-height 3000 --out ../../apps/web/public/models
# 2. Run the viewer
cd ../../apps/web && npm run dev
# 3. Open http://localhost:3000/viewer?model=fixture_b   (default: fixture_a)
```
`--wall-height` (mm) is required when the DXF carries no height. `--out` can be any directory; the `.glb` must end up in `apps/web/public/models/` (git-ignored). The stem may contain only `A-Z a-z 0-9 _ -`.

## Upload workflow (browser)

```
# terminal 1
cd services/api && uv run uvicorn api.main:app --reload
# terminal 2
cd apps/web && npm run dev
```

Open http://localhost:3000, choose a DXF, review the preflight issues, enter
wall height (and units if the DXF has none), then Generate. The viewer opens at
`/viewer?generation=<id>`. Set `NEXT_PUBLIC_API_URL` (web) / `API_CORS_ORIGINS`
and `API_DATA_DIR` (API) to change the defaults.
