# Input Constraints and Benchmark Plan

## 1. Purpose

The application needs practical limits, but arbitrary values should not be invented before testing real drawings. This document records which constraints must exist, how they will be measured and how numeric thresholds will be selected.

**Current status:** Policy decided; numeric limits are intentionally TBD pending benchmark results.

## 2. Phase 0 input policy

| Dimension | Phase 0 policy | Numeric threshold |
|---|---|---|
| File format | DXF only, using a documented subset | Not applicable beyond supported format / version tests |
| File size | Enforce a hard upload / processing limit | TBD by benchmark |
| Drawing extent / area | Enforce a hard maximum supported coordinate extent or area | TBD by benchmark |
| Floors | One floor per generation job | One floor per job; project hierarchy may reference multiple floors later |
| Entity count | No arbitrary user-facing cap; enforce internal resource safeguards | TBD by benchmark |
| Geometry complexity | Enforce limits for pathological / expensive geometry | TBD by benchmark |
| Drawing conventions | Explicitly documented and validated | Defined by fixture tests and domain review |
| Units / scale | Must be known or supplied by user | No generation when unresolved |
| Wall / ceiling heights | Extract only when reliable; otherwise require user input | Values depend on drawing and user input, not one global cap |
| Processing time | Track and enforce a safe operational timeout | TBD by benchmark and hosting environment |
| Memory | Track peak memory and reject / defer work that exceeds safe capacity | TBD by benchmark and hosting environment |

## 3. Drawing conventions to define

Before claiming DXF support, document at least:

- expected units and supported unit conversion;
- coordinate orientation and origin assumptions;
- layer names or layer-mapping mechanism for walls, partitions, floors, openings and columns;
- supported entity types for each category;
- whether walls are represented as paired boundaries, centre lines with thickness, closed polylines or a restricted combination;
- how doors and windows are represented (blocks, gaps, symbols, attributes or other convention);
- handling of arcs, splines, hatches, external references and nested blocks;
- how text and dimension annotations are treated;
- how duplicate / overlapping geometry is handled; and
- which drawing elements are ignored or reported as unsupported.

Do not claim to support a drawing convention simply because the parser can read the entities. The interpretation must also be correct and tested.

## 4. Benchmark dataset

Build a small, legally usable dataset with increasing difficulty:

1. **Fixture A — Simple:** single floor, clean layers, rectangular rooms, explicit units, simple walls and floor boundary.
2. **Fixture B — Moderate:** more rooms, non-rectangular geometry, corners / junctions and representative openings.
3. **Fixture C — Convention variation:** same general building features represented with a different valid layer / entity arrangement.
4. **Fixture D — More complex floor:** larger extent and more entities, still within the intended Phase 0 single-floor workflow.
5. **Fixture E — Multi-storey source set:** multiple floor drawings used to verify that the system processes one floor per job and does not accidentally combine them.
6. **Future fixtures:** large public / institutional / industrial structures, only when licensing, input quality and companion information are understood.

Every fixture must have a source, permission / licence and expected-output note. Online availability does not automatically grant redistribution rights.

## 5. Metrics to record

For every benchmark run, record:

- input file size;
- drawing extent and, when meaningful, plan area;
- number of entities by DXF type;
- number of candidate walls, openings, boundaries and other interpreted elements;
- number of unsupported / ambiguous entities;
- parsing time;
- validation time;
- geometry generation time;
- total processing time;
- peak memory where it can be measured reliably;
- number of validation errors and warnings;
- expected versus generated dimensions;
- geometry validity issues (gaps, overlaps, self-intersections, degenerate faces);
- output GLB size; and
- manual review notes from a domain reviewer.

A fast but incorrect reconstruction is not a successful benchmark result.

## 6. How to choose numeric limits

1. Run the pipeline locally against the benchmark fixtures.
2. Increase one complexity dimension at a time where possible (file size, extent, entity count or geometry complexity).
3. Repeat runs to observe variability.
4. Identify where correctness, processing time or memory begins to degrade.
5. Select a conservative limit below the observed failure boundary, leaving headroom for deployment and concurrent activity.
6. Re-run the suite whenever parser, geometry or hosting configuration changes.
7. Store final values in configuration, not scattered hard-coded constants.

The free Render instance may have much tighter practical limits than local development. Treat local benchmark limits and hosted-demo limits as separate profiles.

## 7. Large structures and future scaling

Do not solve large-structure processing by merely increasing the upload limit. Larger projects may require:

- splitting buildings into floors, wings or zones;
- spatial chunking / tiles;
- stable global coordinates and local chunk coordinates;
- processing only changed zones;
- background jobs and worker processes;
- queue visibility, cancellation and retries;
- streaming or level-of-detail viewer loading; and
- a separate compute environment from the low-cost demo API.

The MVP should preserve project → building → floor structure and stable element identifiers, but should not implement these mechanisms until benchmark evidence supports them.

## 8. Operational safeguards

- Reject invalid or unsupported files before expensive geometry generation.
- Set a configurable maximum upload size.
- Limit parsing / generation time.
- Detect degenerate, duplicate or excessive geometry.
- Clean temporary files after processing.
- Do not trust user-provided file paths or filenames.
- Return a clear explanation when a file exceeds supported limits.
- Avoid accepting work that is likely to crash a shared free-tier process.

## 9. Decision log

| Decision | Status |
|---|---|
| First supported format | DXF |
| Input quality | Clean / structured / documented convention |
| Floors per job | One |
| Numeric file-size cap | TBD after benchmark |
| Numeric drawing-area / extent cap | TBD after benchmark |
| Numeric entity cap | TBD after benchmark; internal guardrail, not arbitrary public feature limit |
| Supported layers / entities | TBD after sample inspection and domain review |
| Processing-time / memory limits | TBD separately for local and deployed profiles |
| Future large-structure approach | Investigate floor / zone chunking and async workers after MVP |
