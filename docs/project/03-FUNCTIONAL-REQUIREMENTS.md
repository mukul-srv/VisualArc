# Functional Requirements

This document defines observable requirements for the first portfolio MVP. Requirements may be refined as input conventions are tested.

Priority labels: **P0** = required for the core demo; **P1** = desirable if the core pipeline is stable; **Future** = intentionally deferred.

## 1. File intake and validation

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-001 | P0 | The user can upload one DXF file for one floor. | A valid supported DXF reaches preflight; a rejected file receives a useful error. |
| FR-002 | P0 | The system validates the extension and actual file readability. | Renaming a non-DXF file to `.dxf` does not bypass validation. |
| FR-003 | P0 | The system checks file size and resource limits. | Inputs beyond the configured benchmarked limit are rejected before expensive processing. The numeric limit remains TBD. |
| FR-004 | P0 | The system reports whether the drawing uses supported conventions. | Unsupported entities / layers are listed or counted with actionable guidance. |
| FR-005 | P0 | The system identifies units / scale where possible. | If not reliable, the user is required to provide or confirm them. |
| FR-006 | P1 | The system preserves basic source metadata. | Layer names and source entity handles/references remain associated with extracted elements where available. |

## 2. Interpretation and canonical model

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-010 | P0 | The parser converts supported drawing entities to a canonical building representation. | A test fixture produces the expected normalized objects. |
| FR-011 | P0 | Every generated structural element has a stable internal ID. | IDs are unique within the project and remain stable during a repeatable processing run where practical. |
| FR-012 | P0 | Important values carry provenance. | A value can be labelled source-extracted, user-provided, defaulted or inferred. |
| FR-013 | P0 | Missing essential parameters are requested from the user. | Generation is blocked when required height / scale / thickness information is missing. |
| FR-014 | P0 | The system distinguishes warnings from blocking errors. | Warnings may be acknowledged; blocking errors prevent generation. |
| FR-015 | P1 | The user can correct supported extraction mistakes before generation. | Corrected values are reflected in the canonical representation and verification report. |

## 3. Geometry generation

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-020 | P0 | The geometry engine creates 3D walls from supported wall geometry. | Test dimensions and wall heights match expected results within documented tolerance. |
| FR-021 | P0 | The engine creates a floor surface for the supported floor boundary. | The generated floor surface matches the test boundary and has no unintended gaps or self-intersections. |
| FR-022 | P0 | The engine preserves openings where the supported source convention identifies them. | An opening fixture produces the expected aperture; ambiguous symbols are flagged rather than guessed. |
| FR-023 | P1 | The engine creates basic columns / other supported repeated elements. | Supported fixture elements generate expected geometry and metadata. |
| FR-024 | P0 | The engine exports a browser-loadable 3D artifact. | A generated GLB can be loaded in the viewer without manual repair. |
| FR-025 | P0 | Geometry generation is independent of the browser viewer. | The backend can generate the same artifact through an automated test or script. |

## 4. Verification and provenance

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-030 | P0 | The user can inspect dimensions of selected elements. | Selecting a supported wall or opening displays its measured dimensions. |
| FR-031 | P0 | The user can inspect where an element came from. | The UI displays source layer/entity or user-input provenance where available. |
| FR-032 | P0 | The system identifies approximate / default / inferred values. | These are visibly differentiated from verified source values. |
| FR-033 | P0 | The system generates a validation report. | Report includes blocking issues, warnings, assumptions and key measurements. |
| FR-034 | P0 | Known measurements are not silently modified. | Automated tests prove that source / confirmed dimensions survive the transformation pipeline. |

## 5. Viewer and navigation

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-040 | P0 | The browser displays the generated model. | A test GLB and a generated GLB both load in the viewer. |
| FR-041 | P0 | The user can orbit, pan and zoom. | Camera controls operate without changing model geometry. |
| FR-042 | P0 | The user can switch between top-down and 3D views. | Both modes show the same underlying model. |
| FR-043 | P1 | The user can navigate in first person. | Movement is constrained sufficiently to avoid falling through or walking through basic walls. |
| FR-044 | P1 | The user can select a model element and view its metadata. | Selection highlights the object and displays associated measurements / provenance. |

## 6. Project and storage workflow

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-050 | P1 | A project can be associated with a user account. | An authenticated user can create and list their own projects. |
| FR-051 | P1 | Project metadata can be persisted in PostgreSQL via Supabase. | A project record can be retrieved after a browser refresh. |
| FR-052 | P1 | Input and output artifacts use persistent object storage. | Stored artifacts remain available independently of Render instance restarts. |
| FR-053 | P1 | Generation status is visible. | User can distinguish queued / processing / completed / failed states, even if initial processing is synchronous. |
| FR-054 | Future | Users can share a read-only project link. | Explicit access control and link revocation are implemented. |

## 7. Non-functional requirements

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| NFR-001 | P0 | Geometry transformations must be deterministic for the same input and parameters. | Repeated test runs produce equivalent canonical geometry and measurement results. |
| NFR-002 | P0 | The engine must be testable without the web UI. | Parser and geometry tests run in the backend test suite. |
| NFR-003 | P0 | Errors must be actionable. | Invalid files and unsupported geometry produce understandable messages, not raw tracebacks. |
| NFR-004 | P0 | The API must validate uploaded input and user-supplied parameters. | Invalid requests are rejected safely. |
| NFR-005 | P0 | The application must not rely on Render's ephemeral filesystem for permanent storage. | Persistent files are stored in object storage. |
| NFR-006 | P0 | Secrets are not committed to Git. | Environment variables / deployment secrets are used. |
| NFR-007 | P1 | The project should run locally from documented commands. | A clean checkout can be installed and launched using the setup guide. |
| NFR-008 | P1 | The system should expose processing metrics. | Benchmark runs record time, memory where measurable, file size, entity count and result quality. |
| NFR-009 | Future | The architecture should support multiple floors and spatial chunking. | The data model has project/building/floor concepts, without requiring distributed processing in MVP. |

## 8. Requirement change control

A new feature should be added to the MVP only when it supports the core value proposition, can be tested with the current input subset, and does not delay the reliable end-to-end pipeline. Otherwise, record it as future scope.
