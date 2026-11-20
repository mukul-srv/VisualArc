# Development Roadmap

## Guiding rule

Build in vertical slices. At every major stage, keep a working, testable result. Claude Code can implement quickly, but each slice must include human inspection, tests and a short understanding checkpoint.

The order below is based on dependencies, not calendar promises. Work should advance when exit criteria are met rather than after an arbitrary number of days.

## Phase 0 — Repository and development foundation

**Goal:** Establish a reproducible workspace.

Tasks:
- create Git repository and initial README;
- create frontend and backend skeletons;
- pin and document runtime / package versions;
- establish linting, formatting and tests;
- add a minimal `CLAUDE.md` with project rules;
- add a tiny sample DXF fixture with permission / licence recorded;
- make both applications run locally.

Exit criteria:
- clean checkout can be installed;
- frontend and API health endpoint start;
- one test command works for each side;
- secrets are excluded from Git.

## Phase 1 — Understand and parse a DXF

**Goal:** Read a supported drawing without generating 3D yet.

Tasks:
- inspect actual sample drawings and their conventions;
- choose the first limited convention;
- implement DXF preflight and entity inventory;
- list layers, entity types, units and extents;
- preserve source handles and metadata;
- create parser fixtures and expected outputs.

Exit criteria:
- parser works on multiple known fixtures;
- unsupported entities are reported;
- parser output is deterministic and testable;
- supported input conventions are documented.

## Phase 2 — Canonical building representation

**Goal:** Convert file-specific entities into a clean internal model.

Tasks:
- define coordinate and unit policy;
- define building / floor / element models;
- define provenance types;
- normalise line and polyline geometry;
- identify supported wall and floor-boundary conventions;
- add validation issues and blocking / warning severity.

Exit criteria:
- known DXF fixture produces expected canonical JSON;
- source references and provenance survive normalisation;
- essential missing inputs are identified.

## Phase 3 — 2D geometry and verification

**Goal:** Prove that extracted geometry is geometrically sensible before adding 3D.

Tasks:
- clean and validate supported linework;
- implement wall centreline / footprint interpretation for the chosen convention;
- implement dimension calculations;
- detect degenerate segments and invalid polygons;
- produce a 2D diagnostic view or report;
- establish tolerances and measurement tests.

Exit criteria:
- test dimensions match expected results within documented tolerance;
- blocking geometric issues are caught;
- corrections to input parameters update the canonical model predictably.

## Phase 4 — 3D geometry engine

**Goal:** Generate the first measurable 3D model.

Tasks:
- implement wall extrusion;
- implement floor surfaces;
- add clearly identified openings where source conventions support them;
- test wall junctions and opening boundaries;
- select and test GLB export tooling;
- associate mesh objects with canonical element IDs.

Exit criteria:
- generated GLB opens in a separate viewer;
- key dimensions match source / user-confirmed inputs;
- geometry tests cover normal and failure cases;
- uncertain dimensions remain labelled.

## Phase 5 — Browser viewer

**Goal:** Explore the generated model.

Tasks:
- build a minimal Three.js scene;
- load generated GLB;
- add orbit / pan / zoom;
- add top-down mode;
- add selected-element metadata panel;
- add first-person navigation if collision / movement can be implemented reliably without delaying core verification.

Exit criteria:
- model loads reliably;
- camera controls work;
- metadata can be inspected;
- viewer does not modify the source model.

## Phase 6 — Full local web workflow

**Goal:** Connect upload, interpretation, correction, generation and viewing.

Tasks:
- add Next.js upload / project interface;
- connect FastAPI endpoints;
- show preflight results and missing parameters;
- add correction form;
- call generation endpoint;
- display progress / status and viewer;
- add end-to-end tests.

Exit criteria:
- an end user can complete the supported workflow locally without manual file manipulation;
- failures are displayed clearly;
- end-to-end test covers one successful and one rejected input.

## Phase 7 — Benchmark and input limits

**Goal:** Determine practical operating limits from evidence.

Tasks:
- curate a small, legally usable benchmark set;
- increase drawing complexity gradually;
- record file size, area, entity count, geometry count, process time, memory and output quality;
- determine safe limits with headroom;
- document accepted conventions and known failure modes.

Exit criteria:
- all user-facing limits have a test basis;
- the application rejects work likely to exceed available resources;
- benchmark procedure can be repeated.

## Phase 8 — Persistence, authentication and deployment

**Goal:** Publish a usable portfolio demo.

Tasks:
- add Supabase Auth if account-based projects are needed;
- add project metadata tables and access policies;
- add persistent file storage;
- deploy Next.js to Vercel and FastAPI to Render;
- configure CORS, environment variables and secrets;
- add health checks, logs and safe error handling;
- test free-tier sleep, cold starts, storage and memory limitations.

Exit criteria:
- public demo works within explicitly documented limitations;
- permanent artifacts survive API restarts;
- private projects cannot be accessed by another user;
- deployment steps are reproducible.

## Phase 9 — Portfolio polish

**Goal:** Make the engineering work easy to evaluate.

Tasks:
- document architecture and key algorithms;
- add benchmark results and known limitations;
- record a demo walkthrough;
- prepare sample inputs and expected outputs;
- include diagrams and screenshots;
- explain which parts were implemented with AI assistance and which engineering concepts were learned / verified.

Exit criteria:
- a reviewer can understand the problem, system boundaries, test methodology and trade-offs;
- the developer can explain and modify core code without relying on an AI-generated explanation.

## Future phases — larger and more complex structures

Possible extensions after MVP stability:
- linked multi-floor buildings and stair navigation;
- multiple wings / buildings and campus-scale coordinate systems;
- zone-based and chunked processing;
- asynchronous job queue and worker pool;
- incremental updates and partial regeneration;
- PDF and additional CAD/BIM adapters;
- imperfect / raster input interpretation;
- richer editing, materials, furniture and landscaping;
- VR / AR and mobile experiences.

## Scope control

Before adding a feature, ask:
1. Does it strengthen geometric reconstruction, verification or the viewer?
2. Does it depend on input conventions that are already tested?
3. Can it be delivered and tested as a small slice?
4. What existing milestone would it delay?

If it does not strengthen the current milestone, record it under future scope.
