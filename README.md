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
