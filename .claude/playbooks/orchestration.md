# Orchestration
- Roadmap/status: `docs/implementation/remaining-work-plan.md` (may be outdated). Before work, check git status, recent commits, relevant code, actual task status.
- Act as coordinator. Delegate substantial, self-contained work to fresh subagents. No agents for trivial tasks; no duplicate investigations or overlapping edits.
- Model per task from the plan. Default: Sonnet routine implementation; Opus geometry algorithms, schema design, complex decisions, critical reviews.
- Parallelize only independent tasks and read-only research/reviews. Keep dependent geometry/schema work sequential.
- Review subagent changes; run relevant tests and the full suite before accepting.
- Do batches of related tasks without asking on routine decisions covered by approved specs.
- Commit locally after review + tests pass; conventional messages. Never push to `main` directly; push feature branches and merge PRs only after review (see Agent workflow).
- Update the plan as task status changes.

## Agent workflow
- Branch per independent task set, off `main`. Open a PR when done. Haiku reviews the PR; escalate to Sonnet only if Haiku escalates. Passing review authorizes merge.
- Before merging: remove the task's worktree if it is not locked.
- If the worktree is locked by a live session, merge with `gh pr merge N --squash` (no `--delete-branch`), then `git push origin --delete <branch>`.
- Tests always run via Haiku.
- Max 3 subagents concurrently, including nested.
- Web typecheck: `npm run typecheck`. Never bare `tsc` in a fresh worktree.
