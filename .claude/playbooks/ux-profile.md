# UX profile (for /ux-overhaul)
## App
- Web `http://localhost:3000` (Next.js, `npm run dev` in `apps/web`); API `http://127.0.0.1:8000` (proxied via `/api/*`).
- API: `cd services/api && uv run uvicorn api.main:app` with `DATABASE_URL=postgresql+psycopg://visual_arc:visual_arc@localhost:5432/visual_arc_agent` (migrated). Never use DB `visual_arc`. Playwright config starts both servers.
- Framework: read `apps/web/node_modules/next/dist/docs/` before routing changes.
## Auth and roles
- Roles: owner/editor/viewer per project (`can`, `tabsFor` in `ProjectParts.tsx`); share links read-only.
- States: `apps/web/e2e/.auth/{owner,viewer}.json`; regenerate: `cd apps/web && npx playwright test --project=setup`.
## Tests
- `cd apps/web`: `npm test`, `npm run typecheck`, `npm run lint`, `npm run e2e`. API: `cd services/api && uv run pytest -q`.
## Docs
- UX docs in `docs/ux/` (local only, gitignored).
## Flow
- Branches `ux/NN-slug` off main; implementer (Sonnet) + reviewer (Haiku) per `.claude/playbooks/orchestration.md`; merge only on green CI + review; never push main; never mark a user checkpoint verified.
## Constraints
- Keep current CSS look; no new visual design. 3D/geometry logic untouched. No new deps beyond `@playwright/test`, `@axe-core/playwright`.
