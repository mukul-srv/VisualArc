# Orchestration
Global orchestration rules: ~/.claude/CLAUDE.md. This file adds project specifics only.

- Plan/status: `docs/implementation/phase-1-plan.md` (local). Check `git log` for actual progress.
- Agents: `implementer` (Sonnet) and `reviewer` (Haiku) in `.claude/agents/` hold the standing rules; dispatch prompts give only the subtask and new facts.
- One warm implementer per section; resume it per subtask. Geometry/schema work stays sequential.
- Opus (plan mode) designs geometry algorithms and schema changes before a section starts.
- CI (`.github/workflows/ci.yml`) is the test gate. Merge = green CI + passing reviewer.
- Agents never use DB `visual_arc` (user's dev DB); they use `visual_arc_agent`.

## Merge flow
- Merge with `gh pr merge N --squash`, then `git push origin --delete <branch>`; remove finished worktrees.
- Remote branch deletion after merge is approved; deleting any other remote branch needs user approval.
- Web typecheck: `npm run typecheck`. Never bare `tsc` in a fresh worktree.
