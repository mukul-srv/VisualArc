# Orchestration
Global orchestration rules: ~/.claude/CLAUDE.md. This file adds project specifics only.

- Roadmap/status: `docs/implementation/remaining-work-plan.md` (may be outdated). Before work, check git status, recent commits, relevant code, actual task status.
- Act as coordinator. Parallelize only independent tasks and read-only research/reviews. Keep dependent geometry/schema work sequential. No overlapping edits.
- Model roles: Opus plans and reviews design decisions; Sonnet implements geometry/schema work; complex PR review: Haiku first, Sonnet if Haiku fails.
- Review subagent changes; run relevant tests and the full suite before accepting.
- Do batches of related tasks without asking on routine decisions covered by approved specs.
- Commit locally after review + tests pass; conventional messages. Never push to `main` directly; push feature branches and merge PRs only after review.
- Update the plan as task status changes.

## Merge flow
- Before merging: remove the task's worktree if it is not locked.
- If the worktree is locked by a live session, merge with `gh pr merge N --squash` (no `--delete-branch`), then `git push origin --delete <branch>`.
- Remote branch deletion after merge is part of the approved merge flow; deleting any other remote branch needs user approval.
- Web typecheck: `npm run typecheck`. Never bare `tsc` in a fresh worktree.
