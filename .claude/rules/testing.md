---
paths:
  - "services/api/tests/**"
  - "apps/web/**/*.test.*"
---
# Testing rules
- Every task needs acceptance criteria and relevant tests.
- Run relevant tests, then the full applicable suite, before accepting work.
- API: `cd services/api && uv run pytest`. Web: `cd apps/web && npm test`.
- Never weaken tests to hide bugs. Never hardcode fixture coordinates to pass.
