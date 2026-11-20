# ADR-001: Canonical units and coordinate system

**Date:** 2026-11-19 · **Status:** accepted

## Context
DXF drawings carry units via `$INSUNITS` (often unset) and use a 2D plan X/Y plane. glTF/GLB is metres, Y-up, right-handed. Geometry and tests need one unambiguous convention.

## Decision
- Canonical model stores lengths in **millimetres** (architectural norm, integer-friendly).
- Canonical plan axes = DXF X/Y. Elevation = Z (up).
- GLB export converts mm -> m and maps plan (x, y, z_up) -> glTF (x, z_up, -y).
- Units must be known from `$INSUNITS` or supplied by the user; unresolved units block generation.

## Alternatives
- Metres canonical: matches glTF, but source dims become floats like 0.2 and tests read worse.
- Keep source units: every algorithm needs unit awareness; more error-prone.

## Consequences
- Single conversion point in the GLB exporter.
- Viewer works in metres; 1 grid cell = 1 m.
