# apps/web (Next.js + Three.js viewer)

Browser viewer for engine output. Never duplicates parsing or geometry rules (those live in `services/api/`).

## Commands
- Dev: `npm run dev` · Test: `npm test` · Typecheck: `npm run typecheck`
- Lint: `npm run lint` · Build: `npm run build`
- Next.js has breaking changes: read `node_modules/next/dist/docs/` first (see AGENTS.md).

## Worktree tip
Fresh worktree: don't `npm ci` unless the lockfile differs from main. If `apps/web/package-lock.json` matches main, link main's deps (PowerShell, from repo root):
`New-Item -ItemType Junction -Path apps/web/node_modules -Target <main-repo>/apps/web/node_modules`
