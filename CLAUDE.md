# CLAUDE.md

Portfolio project: restricted DXF floor plans → canonical building model with provenance → 3D GLB → browser viewer. Verification-first.

## Structure
- `services/api/`: Python engine + FastAPI. Area rules and commands: `services/api/CLAUDE.md`.
- `apps/web/`: Next.js + Three.js viewer. Area rules and commands: `apps/web/CLAUDE.md`.
- `fixtures/`: input DXFs, expected outputs, `LICENCES.md`.
- `docs/` (local only): `project/` specs, `implementation/` plans (`remaining-work-plan.md` = roadmap), `architecture/decisions/` ADRs, `learning/` Obsidian vault.

## Always
- Implement only agreed scope. No unrelated refactors or new dependencies. Free/open-source only; ask before paid services.
- Never guess, silently discard unsupported geometry, or alter known measurements. Record unsupported inputs and uncertainty explicitly.
- Never claim tests passed unless run. Never weaken tests or hardcode fixture coordinates.
- Never push to `main` directly. Push feature branches and merge their PRs only after review, per `.claude/playbooks/orchestration.md`. Never mark a manual checkpoint verified.
- Keep replies concise.

## Load on demand (Read the file only when the task matches)
- Nested `CLAUDE.md` files load automatically when working inside their folder.
- Auto-loaded by path (`.claude/rules/`): `geometry.md` (engine code), `testing.md` (tests), `learning-notes.md` (docs/learning).
- Read manually (`.claude/playbooks/`):
  - `orchestration.md`: planning, delegating to subagents, commits, task status.
  - `checkpoints.md`: before stopping for user input or making architecture/domain decisions.
  - `reporting.md`: before writing the end-of-batch report.
