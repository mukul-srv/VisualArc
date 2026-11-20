# T21 benchmark report and proposed limits (for MC-8)

## MC-8 decisions (user, 2026-11-21)

1. The proposed limits are **approved provisionally for the local MVP** and now
   **enforced** (T21a): 600 wall-layer segments, 120 opening markers, 5,000 total
   entities, 5 MiB file size; rejected before interpretation (CLI exit 3, API 422).
2. **No 60 s job timeout and no worker-subprocess architecture yet.** Both are a
   **requirement before hosted deployment (T24)**, not optional.
3. **No broad engine optimisation now.** The bottlenecks below are **known technical
   debt**; this report is their evidence. Re-run `scripts/benchmark.py` after any change
   to parser/geometry/hosting before raising a limit.
4. All limits are **provisional**: the inputs are synthetic and regular and were not
   validated against representative architectural drawings or hosted infrastructure.

The rest of this document is the original proposal and evidence (written before the
decisions above; "Nothing below is enforced yet" is superseded by decision 1).

Date: 2026-11-20/21. Code under test: commit `3c738e0` (engine unchanged since).
Raw data: `benchmarks/t21-results.json`, `benchmarks/t21-diagnostic-no-plugs.json`.
Reproduce: `cd services/api && uv run python ../../scripts/benchmark.py`
(diagnostic series: add `--diagnostic-no-plugs`). Generator: `scripts/make_fixture_d.py`.

## Headline

1. **Processing time is the binding constraint, not file size or memory.** It grows
   roughly with the **cube** of the number of wall pieces (exponent 2.85 between 25 and 49 tiles).
   A drawing of ~3,300 entities (64 tiles, 559 KB) takes **340 s**; ~5,200 entities
   (100 tiles, 866 KB) did not finish in **1,200 s** (killed).
2. **The dominant cause is one loop**, `_plugs` in `geometry2d/openings.py` (T11): three
   nested loops over all paired walls (`for p / for wa / for wb`), O(W³), where W is the
   number of wall pieces BEFORE opening merge (18 per tile; the 'Walls' column shows the
   merged count). A profile of the 16-tile input shows 15 of 17.7 s inside it (40.9 M
   calls of `_geom`, consistent with ~288³ x 2).
3. With that check disabled (diagnostic; output identical for this fixture, but treat
   as a timing experiment) growth is still super-linear, with a local exponent that
   rises from about 2.05 to 2.27 across the series: 144 tiles / 7,488 entities took
   **127 s**. Fixing `_plugs` alone would not make the engine scale.
4. Everything else is cheap and well-behaved: parse is linear (0.16 s at 559 KB),
   3D geometry ~0.7 s at 3,328 entities, GLB export 0.14 s, **peak working set 99 MB** at
   3,328 entities (136 MB at 7,488 in the diagnostic run), GLB 1.21 MB (sizes in this
   report are decimal KB/MB, 1 MB = 1,000,000 B).
5. **Correctness held at every size that finished**: element counts equal N x the
   per-tile counts exactly, 0 blocking issues, all wall/opening solids watertight,
   wall thickness exact (error 0.0 mm), and geometry unchanged at coordinate offsets
   up to 1e8 mm (100 km).

The engine is correct but **not safe to expose to arbitrary drawings**: a plausible
mid-size file blocks a worker for many minutes. A guard is required, and the
`_plugs` loop should be fixed before limits are finalised (see Proposed limits).

## Method

- Input ("Fixture D"): `fixtures/input/fixture_openings.dxf` (3 rooms, 10 merged walls,
  7 openings, 3 floors, 52 entities, 9.6 x 4.0 m) copied N times on a k x k grid with a
  1,000 mm gap (> `wall_thickness_max_mm` 600, so tiles never pair). Expected counts
  are exactly N x (10 walls, 8 junctions, 3 floors, 7 openings): the result is checked,
  not just timed. Committed `fixtures/input/fixture_d.dxf` is the 3 x 3 (9 tiles) case;
  larger sizes are generated on demand.
- One complexity dimension at a time: **entity/wall count** (k = 1..10; tiles also
  grow the extent, which the extent probe shows is harmless) and **coordinate
  magnitude** (one tile translated 0 .. 1e8 mm).
- Each run is a **fresh subprocess** (peak memory is per run). Stages timed with
  `time.perf_counter`: parse (`load_doc`), interpret (`read_dxf` minus parse; includes
  pydantic validation, which is not separable), 3D geometry, GLB export, meta, report,
  canonical JSON. Peak memory = OS peak working set of the child (Windows
  `GetProcessMemoryInfo`; includes shared pages and can be trimmed by the OS, so it is a
  guide rather than a container-limit figure). `total` = interpret pipeline + geometry + export + meta + report.
- Repeats: 3 runs for sizes whose first run was <= 60 s; larger sizes once (time
  budget). Observed run-to-run spread where repeated: up to ~13 % (9 tiles 1.42-1.61 s; 16 tiles
  6.48-7.23 s), so differences under ~15 % are noise. Sizes from 36 tiles up, which decide
  the limits, are single runs.
- Environment: Windows 11 (10.0.26200), AMD64 Family 25 (16 logical cores), 15.2 GiB
  RAM, Python 3.12.6, ezdxf 1.4.5, shapely 2.2.0, trimesh 5.2.1, pydantic 2.14.4.
  Single-process, single-thread workload; other applications were running.

## Results: entity scale (engine as shipped)

| Tiles | Entities | DXF | Walls / openings | Total (median) | Parse | Interpret | 3D | Peak RAM | GLB | Runs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 52 | 27 KB | 10 / 7 | 0.04 s | 0.01 | 0.01 | 0.02 | 74 MB | 21 KB | 3 |
| 4 | 208 | 52 KB | 40 / 28 | 0.24 s | 0.02 | 0.15 | 0.05 | 76 MB | 76 KB | 3 |
| 9 | 468 | 94 KB | 90 / 63 | 1.47 s | 0.03 | 1.29 | 0.11 | 79 MB | 170 KB | 3 |
| 16 | 832 | 153 KB | 160 / 112 | 6.61 s | 0.04 | 6.22 | 0.22 | 81 MB | 301 KB | 3 |
| 25 | 1,300 | 229 KB | 250 / 175 | 22.8 s | 0.05 | 22.3 | 0.30 | 86 MB | 471 KB | 3 |
| 36 | 1,872 | 322 KB | 360 / 252 | 63.0 s | 0.08 | 62.3 | 0.42 | 91 MB | 678 KB | 1 |
| 49 | 2,548 | 432 KB | 490 / 343 | 155.8 s | 0.11 | 154.8 | 0.59 | 96 MB | 922 KB | 1 |
| 64 | 3,328 | 559 KB | 640 / 448 | 340.2 s | 0.16 | 338.9 | 0.74 | 99 MB | 1.21 MB | 1 |
| 100 | 5,200 | 866 KB | - | **> 1,200 s (killed)** | - | - | - | - | - | 1 |

Every finished row: counts equal expected, 0 blocking issues (4 warnings: defaulted
elevation/opening dimensions, ignored door swings), all solids watertight, thickness
error 0.0 mm.

## Results: diagnostic, jamb-pair check disabled (timing experiment)

| Tiles | Entities | Total | Interpret | 3D | Peak RAM | GLB |
|---:|---:|---:|---:|---:|---:|---:|
| 16 | 832 | 1.4 s | 1.1 | 0.23 | 81 MB | 0.30 MB |
| 36 | 1,872 | 6.4 s | 5.7 | 0.44 | 92 MB | 0.68 MB |
| 64 | 3,328 | 21.4 s | 20.1 | 0.78 | 101 MB | 1.21 MB |
| 100 | 5,200 | 55.8 s | 53.5 | 1.4 | 118 MB | 1.89 MB |
| 144 | 7,488 | 127.4 s | 124.4 | 1.7 | 136 MB | 2.72 MB |

Single runs. Local exponent 2.05 -> 2.27: further quadratic-or-worse steps remain in
interpretation. By code reading (not profiled): `_gaps` tests collinear wall pairs against
all walls with shapely and is re-run on each pass of the `_analyse` fixpoint loop; wall
pairing is pairwise by design (T5); opening association and the face search scan all gaps/
segments per marker. The tile grid makes the collinear-group steps look worse than a
typical plan, because tiles on the same grid line form long collinear groups.

## Results: coordinate magnitude (extent probe)

One tile translated by 0, 1e5, 1e6, 1e7, 1e8 mm: counts match, thickness error 0.0 mm,
solids watertight, time 0.04-0.05 s at every offset. No degradation up to 100 km from
the origin (float round-off remains far below the 1e-6 mm tolerance in this fixture).

## Fixture E (multi-storey source set)

Three storeys = three drawings (`fixture_a`, `fixture_openings`, `fixture_b`), each its
own upload and generation through the API (`tests/test_fixture_d_e.py`). Verified: jobs
are distinct, each has the same element counts as processing the drawing alone, ids restart
at `wall-001`/`floor-0` per job, and a job's result is identical regardless of what was
processed before. **Known limitation (pinned by a characterisation test):** two plans drawn
side by side in ONE DXF are silently interpreted as ONE floor (no warning), i.e. the
system does not detect a multi-storey drawing.

## Proposed limits (for your approval at MC-8)

Principle: a conservative bound below the observed failure boundary, with headroom,
one configuration value each (`Settings` / `--max-*` flags), enforced BEFORE expensive
processing with a clear message (exit 3 / HTTP 422). **Nothing below is enforced yet.**

**Review finding that shapes these limits:** run time follows the number of wall pieces,
not the total entity count. Fixture D has 36 wall LINEs, 18 wall pieces and 7 opening
markers in 52 entities. A file of 1,000 entities that are all wall lines would carry
~500 wall pieces versus ~350 for 1,000 benchmark entities (1.45x), i.e. ~3x the time
(cubic); the ratio worsens as the wall share of the drawing grows. Text,
dimensions and hatch entities cost almost nothing but would consume an entity cap. So the
cap must be on the quantities that drive cost.

| Limit | Proposed (engine as is) | Evidence / reasoning |
|---|---|---|
| **Wall-layer segments** (LINE + polyline edges on the wall layer; counted after parse, before interpretation) | **600** (~300 wall pieces) | Fixture D: 576 segments (16 tiles) = 6.6 s; 900 (25 tiles) = 22.8 s; 1,296 (36) = 63 s. 600 is predicted ~7.5 s, i.e. ~4x headroom to a 30 s interactive budget for slower hosts. Cubic law measured only on this regular layout. |
| **Opening markers** (closed polylines on door/window layers) | **120** | Derived from the fixture ratio (7 markers per 36 segments, so 600 segments ~ 117 markers). Marker count was NOT varied independently; this is a ratio, not a measured limit. |
| **Total modelspace entities** (backstop only) | **5,000** | Non-wall entities were not benchmarked in isolation (parse is linear: 0.16 s at 3,328 entities). Provisional; revisit with a drawing that is mostly annotation. |
| **Max DXF file size** | **5 MiB** (from provisional 50 MiB) | Backstop. Parse ~0.3 s/MB, so even 50 MiB would parse in ~15 s, but would carry far more entities than the caps above allow; file size is a poor proxy (synthetic ratio ~170 B/entity). Parse/memory at 5 MiB was not measured (largest tested file 1.24 MB). |
| **Wall-clock job limit** | **60 s** hard stop | The only true bound for inputs the counts miss. Not enforceable while the API is synchronous in-process: needs a worker subprocess. Until then the count caps are the only protection. |
| Drawing extent / coordinates | **No cap**; tested envelope: offsets to 1e8 mm, footprint up to ~85 x 40 m | No degradation measured (counts, thickness, watertightness, time). A cap would be arbitrary. |
| Peak memory | **No cap** | 74 MB baseline, 99 MB at 3,328 entities, 136 MB at 7,488; well below a 512 MB instance. Re-check on the hosted profile. |
| GLB size | **No cap** | 1.21 MB at 3,328 entities. Browser load/render time NOT benchmarked. |
| Floors per job | One (unchanged) | Fixture E. Add a warning for multi-plan files as a follow-up. |

**If the O(n^2+) interpretation steps are optimised** (a `_plugs` fix alone is not
enough, see above), the segment cap could rise substantially; the diagnostic series
suggests a few-fold at best until `_gaps`/pairing are also addressed. Any raise must come
from a re-run of this benchmark on the changed code, not from this report.

**Hosted (Render free) profile: NOT measured.** All numbers are one local machine
(16 cores, 15 GiB). The free instance has far less CPU and 512 MB RAM; its limits must be
benchmarked there at deployment (T24) and may be tighter than the local ones.

## Recommended sequence (needs your decision)

1. Approve or adjust the limits above.
2. Implement enforcement (segment/marker/entity/file-size caps with clear messages; job
   time limit once work moves off the request thread) as a small follow-up task.
3. Separately decide whether to optimise interpretation (`_plugs` O(W^3) first: look up
   walls by end-cap position rather than scanning all triples; then `_gaps`, pairing and
   marker association) and re-run this benchmark. I have not changed engine code.

## Limitations of this benchmark

- Synthetic, perfectly regular input (one fixture replicated). Real drawings differ in
  entities per wall, curved/ignored entities, layers; cost per entity may be higher or
  lower. A real-world drawing set (licensed, T21 "future fixtures") is not included.
- **No domain-reviewer notes** on the larger fixtures (listed in the doc 08 metrics);
  correctness evidence is automated (counts, watertightness, thickness) plus your
  earlier visual checks of the small fixtures; Fixture D was not visually inspected.
- Single runs from 36 tiles up; no variance estimate there. Machine was not idle.
- Doc 08 section 5 metrics not recorded: plan area/extent in the JSON, expected-vs-generated
  for wall lengths and opening widths/offsets (only thickness and element counts are
  checked), geometry validity beyond watertightness (self-intersection, degenerate faces).
  Doc 08 section 6: file size and geometry complexity were not varied separately from
  entity count; Fixtures A-C were not run in this harness. Block INSERT expansion was not
  checked (modelspace entity counts could understate work if the reader expanded blocks).
- Browser-side performance (load time, frame rate with ~1-3 MB GLBs, selection raycast
  cost) not measured.
- Validation time is not separable from interpretation; "unsupported/ambiguous entity"
  counts are 0 in these inputs (only the 4 standard warnings), so degraded-input
  behaviour (many unmapped entities, many ambiguous pairings) is not benchmarked.
- Peak memory is the OS working-set peak of a fresh process, including the ~74 MB
  interpreter + library baseline.
