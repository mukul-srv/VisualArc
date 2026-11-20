# Development Starting Point

## 1. Start with a narrow technical proof

Do not begin by generating the full web application. First prove that one supported DXF drawing can be parsed, normalised and turned into a simple 3D artifact.

The first milestone is intentionally small:

**DXF file → entity inventory → canonical JSON → simple wall / floor mesh → GLB → minimal Three.js viewer.**

Only after this works should the upload workflow, accounts, database and deployment be added.

## 2. Before coding

1. Create a GitHub repository.
2. Create a local project folder and initialise Git.
3. Install the runtimes and tools required by the chosen frontend / backend versions.
4. Create one small DXF sample that you are allowed to use and document its source / licence.
5. Inspect the sample in a DXF viewer or CAD tool to understand its layers, units and entities.
6. Create a short `CLAUDE.md` using the policy in the learning guide.
7. Ask Claude Code to inspect the empty repository and propose the smallest setup plan; do not ask it to build the whole product in one prompt.

## 3. First implementation sequence

### Task 1 — Repository skeleton

Create only:
- frontend starter application;
- Python backend package;
- a health endpoint;
- test configuration;
- `.gitignore` and `.env.example`;
- concise root `CLAUDE.md`.

Verify both apps start and tests run.

### Task 2 — DXF inspection script

Create a command-line script that reads a sample DXF and prints:
- file units / header information where available;
- layer names;
- entity counts by type;
- drawing extents;
- source handles for relevant entities.

Do not generate walls yet. The goal is to see what information is actually present in the file.

### Task 3 — Choose the first drawing convention

Inspect a few sample plans. Decide which layer / entity patterns will count as supported. Ask an architect or architecture student to review the convention assumptions. Write them down in the input constraints document.

### Task 4 — Canonical representation

Design the smallest canonical model that represents the selected fixture. Include units and provenance from the beginning. Add tests for its serialised JSON output.

### Task 5 — Basic geometry

Start with a simple known wall segment and known floor boundary. Implement and test unit conversion, wall thickness, wall height and extrusion. Do not start with complicated room topology or every architectural symbol.

### Task 6 — Export and viewer proof

Export a basic GLB and load it in a minimal Three.js scene. Verify scale, orientation and dimensions. Add a visual axis / grid during debugging so coordinate mistakes are easy to spot.

### Task 7 — Expand through fixtures

Only after the first fixture is correct, add a second drawing with one additional supported feature. Add a regression test before expanding further.

## 4. First acceptance checklist

- [ ] DXF parser reads the sample file.
- [ ] Entity inventory matches what is visible in the source drawing.
- [ ] Units and coordinate conventions are explicit.
- [ ] Canonical JSON preserves source references.
- [ ] A known wall can be generated with the expected length, thickness and height.
- [ ] A floor boundary can be generated without invalid geometry.
- [ ] Exported model loads in a browser viewer.
- [ ] Test commands are documented.
- [ ] The developer can explain the data flow and coordinate / unit handling.

## 5. Things not to do at the beginning

- Do not add Supabase authentication before the local pipeline works.
- Do not build a generic plugin system for many file formats.
- Do not attempt raster plan recognition.
- Do not implement every door / window symbol.
- Do not build a complex queue or worker architecture before measuring processing needs.
- Do not add furniture, lighting design, landscaping or photorealism.
- Do not ask Claude Code to create the entire application in a single task.
- Do not accept code that passes one fixture by hardcoding its coordinates or dimensions.

## 6. Suggested first Claude Code request

```text
We are starting a portfolio project that converts a restricted, supported subset of
architectural DXF floor plans into a measurable 3D model.

Read only the project overview and the development starting-point document. Inspect
the repository, but do not edit files yet.

Propose the smallest repository setup needed for the first technical proof:
DXF inspection script -> canonical JSON -> simple geometry -> GLB -> minimal viewer.

For each proposed file, state its responsibility in one sentence. Identify assumptions
that need my decision. Keep the response concise and do not implement anything until
I approve the plan.
```

## 7. First proof before the user interface

The first deliverable should be a short repeatable script and a sample output, not a polished website. This isolates the hardest uncertainty—the quality of drawing interpretation and geometry—from frontend and deployment concerns.
