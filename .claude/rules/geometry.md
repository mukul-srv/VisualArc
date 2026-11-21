---
paths:
  - "services/api/src/api/engine/**"
  - "fixtures/**"
---
# Geometry engine rules
- Canonical units: millimetres.
- Plan X/Y → GLB X/-Z, Y-up (ADR-001).
- Initial DXF convention: paired parallel lines on `A-WALL`; closed LWPOLYLINE on `A-FLOR`; orthogonal walls only. See Document 08 §3a.
- Thresholds and tolerances live in `engine/settings.py` (ADR-003). No magic numbers.
- Preserve provenance: `source_extracted`, `user_provided`, `defaulted`, `inferred`.
- Keep the engine independently testable from the viewer.
- Numerical resource limits come from benchmarks, not assumptions.
