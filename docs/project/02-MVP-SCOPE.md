# MVP Scope

## 1. MVP objective

Deliver one reliable end-to-end vertical slice: **a supported single-floor DXF drawing enters the system, becomes a verified intermediate representation, is converted into 3D geometry, and can be explored in the browser.**

The MVP prioritises geometric traceability and a working open-source-oriented reconstruction engine over a large feature list.

## 2. In scope

### A. Input and preflight

- Upload one DXF file per generation job.
- Check file type, readability and documented entity / layer conventions.
- Extract units, layers, blocks and supported geometric entities where available.
- Ask the user to provide or confirm scale / units when the drawing does not provide reliable information.
- Report unsupported entities and blocking ambiguities.

### B. Interpretation and correction

- Convert supported source entities into a canonical building representation.
- Preserve source entity handles or stable source references where possible.
- Classify each important value as source-extracted, user-provided, defaulted or inferred.
- Show extracted dimensions and validation warnings.
- Allow the user to supply required global parameters such as wall height and, where not recoverable, wall thickness or floor elevation.
- Require resolution of blocking issues before generation.

### C. Geometry generation

- Generate basic floor surfaces and wall geometry from supported input geometry.
- Represent openings when the supported drawing convention identifies them reliably.
- Support basic columns or other repeated structural elements only if their representation is unambiguous in the chosen input subset.
- Keep geometry generation separate from file parsing and the browser viewer.
- Generate a basic 3D model and export GLB once the pipeline is stable.

### D. Verification

- Display dimensions for selected generated elements.
- Compare selected model measurements with the source / user-confirmed measurements.
- Display provenance for selected elements.
- Report warnings, unsupported elements and approximations.
- Never alter known source or user-confirmed dimensions merely to improve appearance.

### E. Browser viewer

- Render the generated model in Three.js.
- Provide orbit, pan and zoom controls.
- Provide a first-person navigation mode with keyboard and mouse controls if it can be delivered without compromising core geometry work.
- Provide top-down and 3D viewing modes.
- Use simple materials and lighting.
- Allow the user to inspect a floor independently.

### F. Basic project workflow

- A simple project record and generation status.
- Basic authentication and project metadata using Supabase may be added after the local end-to-end pipeline works.
- Store persistent uploads and generated artifacts outside Render's temporary filesystem.

## 3. Explicitly out of scope

- DWG, SKP, IFC, OBJ, GLB or image files as alternate plan-reconstruction inputs.
- Raster image / photo / scanned-plan recognition.
- Automatic interpretation of arbitrary drawing conventions.
- Full building-wide multi-floor connectivity.
- Unlimited-scale campus / hospital / industrial-site processing.
- Furniture placement, interior decoration, landscaping and material catalogues.
- Photorealistic rendering.
- Wall / room redesign and free-form architectural editing.
- Electrical, plumbing, HVAC and detailed structural engineering interpretation.
- Real-time multi-user collaboration.
- VR / AR and native mobile applications.
- Contractor estimates, quotations or construction management.
- Paid AI or cloud geometry APIs.

## 4. Input format decision

DXF is the first format because it is a structured exchange format and can be parsed with open-source tooling. The MVP will support a deliberately documented subset, not every valid DXF feature.

PDF is a likely second adapter, but must be split into at least two cases:

- vector PDF where lines and text can be extracted; and
- raster PDF where the page is essentially an image and requires image interpretation.

These should not be silently combined into one implementation. DWG is deferred because of additional format and tooling considerations. Importing GLB is a viewer feature, not proof that the application can reconstruct a building from a floor plan.

## 5. Accuracy policy

- Known dimensions are authoritative unless the user explicitly edits or replaces them.
- Missing dimensions are not fabricated as facts.
- A default value must be visibly labelled as a default.
- Inferred geometry must be marked as inferred and must be reviewable.
- Visual styling may change appearance but must not alter verified geometry.
- If uncertainty blocks a structurally meaningful result, the system must stop and ask for correction.

## 6. Accuracy modes

Do not implement separate accuracy modes in the first MVP. Start with one rule: preserve all verified geometry and make uncertain parts explicit. A later release can offer different presentation or approximation preferences, but no mode may override known measurements.

## 7. Floors and building size

- The initial generation unit is one floor per job.
- Users can explore the generated floor independently.
- Stairs may be represented as geometry if they are clearly present and supported, but cross-floor traversal is not an MVP requirement.
- No arbitrary public-facing floor or entity cap is selected yet. Practical processing limits will be measured and documented.
- Large structures remain future scope. The initial data model should retain a project / building / floor hierarchy so later expansion does not require a complete conceptual rewrite.

## 8. MVP release stages

### MVP-0: Technical proof

A local script accepts a small, known DXF fixture, extracts supported geometry and produces a basic 3D artifact. No account system or polished UI.

### MVP-1: Usable local application

A local web interface uploads a DXF, shows extraction results and parameters, generates a model and displays it in the viewer.

### MVP-2: Verification-first portfolio demo

Add measurement inspection, provenance, warnings, test fixtures, reproducibility documentation and a small benchmark report.

### MVP-3: Public demo deployment

Deploy frontend and API on selected free tiers, add minimal authentication / storage where needed, and clearly communicate demo limitations.

## 9. MVP acceptance gate

Do not call the MVP complete merely because one drawing renders. It must pass:

- valid-input tests;
- unsupported-input tests;
- unit / scale tests;
- geometry consistency tests;
- source-to-model provenance tests;
- viewer smoke tests; and
- benchmark tests on multiple drawings that follow the documented conventions.
