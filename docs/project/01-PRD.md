# Product Requirements Document (PRD)

## 1. Project identity

**Working title:** Architectural Plan-to-3D Reconstruction and Verification Engine  
**Project type:** College / technical portfolio project  
**Product ambition:** An open-source-oriented engine and browser viewer that turn supported 2D architectural drawings into measurable, inspectable 3D geometry.

This is not currently being positioned as a startup or commercial product. The primary objective is to build a technically credible portfolio project, demonstrate engineering judgement, and understand the complete pipeline from drawing data to a navigable 3D scene.

## 2. Problem statement

Architectural floor plans communicate spatial arrangements through lines, symbols, dimensions, layers and drawing conventions. People who are not accustomed to reading plans can struggle to understand how those drawings translate into a physical space. A 3D walkthrough helps with spatial interpretation, but a visually convincing model can still be misleading if its geometry does not faithfully reflect the drawing.

The project explores a more verifiable approach: convert supported drawings into 3D geometry while retaining the relationship between generated elements and their source information. The user should be able to inspect dimensions, identify assumptions and see which parts of the model were extracted, supplied manually or inferred.

## 3. Product vision

Build a modular reconstruction engine that:

1. accepts a documented subset of architectural drawing formats and conventions;
2. extracts and normalises geometric information;
3. asks for essential missing information rather than silently guessing;
4. creates a structured intermediate building model;
5. generates a 3D model from that representation;
6. exposes measurements and provenance so users can verify the result; and
7. makes the result explorable in a browser.

The engine should be reusable and open-source-oriented. The browser application is the demonstration interface for the engine, not the only possible consumer of it.

## 4. Target users for the portfolio demonstration

- **Primary demonstrator:** The project developer, learning and validating each part of the pipeline.
- **Reviewer:** A software / computer science interviewer, faculty member or technical reviewer assessing architecture, implementation quality and problem-solving.
- **Domain reviewer:** An architect or architecture student who can assess whether the input assumptions, extracted dimensions and generated geometry make sense.
- **Demo user:** Someone who can upload a supported plan and inspect the resulting space without needing CAD software.

These are demonstration audiences, not validated customer segments.

## 5. Core value proposition

**A measurable 3D reconstruction whose geometry can be traced back to the drawing—not merely a plausible-looking walkthrough.**

The project will distinguish between:

- values read from the source drawing;
- values entered or confirmed by the user;
- values supplied from an explicitly documented default; and
- values inferred by the reconstruction process.

Known measurements must not be changed to make the model look more attractive.

## 6. Product principles

1. **Geometry before decoration.** Correct structure and dimensions come before materials, furniture and photorealistic rendering.
2. **Verification before confidence.** Unknown or ambiguous geometry must be surfaced, not quietly presented as certain.
3. **Deterministic core.** The initial reconstruction pipeline should be based on explicit geometry rules and testable algorithms, not a paid generative-AI API.
4. **Open formats and replaceable components.** Prefer open-source libraries and a documented internal representation.
5. **Small, testable increments.** Build one working vertical slice at a time.
6. **Portfolio quality includes understanding.** AI may accelerate implementation, but the developer must be able to explain the architecture, data flow, major algorithms and important trade-offs.
7. **Future scale without premature complexity.** Preserve a path toward multi-floor and large structures without implementing distributed processing in the MVP.

## 7. User journey

1. Open the web application.
2. Upload a supported single-floor drawing.
3. The system checks the file and reports whether its format and conventions are supported.
4. The system extracts drawing entities and produces a preliminary interpretation.
5. The user reviews extracted measurements and supplies missing required values such as units, scale or wall height.
6. The system displays validation issues and asks the user to resolve blocking ambiguities.
7. The user starts 3D generation.
8. The system generates a model and a verification report.
9. The user opens the model in the browser, switches between top-down and 3D views, navigates through the space and inspects measurements and element provenance.
10. The user can download the generated model in an open 3D format when export is included in the MVP release.

## 8. Initial input and output

### Initial input

- **Primary first format:** DXF, restricted to a documented and tested subset of entities and conventions.
- **Input quality:** Clean, structured drawings with known units or a way for the user to provide scale.
- **Initial processing unit:** One floor per generation job.
- **Not initially supported as reconstruction inputs:** DWG, raster scans / photographs, SketchUp files, IFC, OBJ and GLB. A 3D file is not equivalent to a 2D-plan reconstruction input.
- **PDF:** A later input adapter. Vector PDFs and raster PDFs require different processing approaches and should not be treated as one easy format.

### Initial output

- A structured intermediate building representation.
- A generated 3D scene with supported walls, floor surfaces, openings and other elements only where the source conventions are sufficiently clear.
- A browser-viewable model.
- A verification report containing measurements, source references, assumptions and unresolved issues.
- GLB export after the core model pipeline is reliable.

## 9. MVP success criteria

The MVP is successful when a reviewer can:

- upload a valid drawing that follows the documented DXF subset;
- see a clear explanation of extracted entities and any missing information;
- correct or supply required parameters;
- generate a model without the system silently changing known dimensions;
- compare key model measurements with drawing measurements;
- identify which model elements came from which source entities or user inputs;
- navigate the result in a browser; and
- reproduce the result using documented local setup and test instructions.

Success is measured with a small benchmark set of drawings of increasing complexity, not with a claim that every architectural drawing is supported.

## 10. Non-goals

The initial project is not:

- a replacement for CAD or BIM authoring software;
- a certified architectural, structural or construction-documentation tool;
- a surveying or as-built measurement system;
- a photorealistic interior-design application;
- an automatic solution for every drawing convention;
- a full building information modelling platform;
- a collaboration or contractor-management product; or
- a startup validation exercise.

## 11. Future direction

After the MVP, possible extensions include:

- linked multi-floor buildings and vertical circulation;
- PDF and additional CAD/BIM adapters;
- more drawing conventions and imperfect input handling;
- large and complicated structures such as hospitals, universities, malls, offices and industrial facilities;
- spatial chunking, incremental generation and level-of-detail strategies;
- richer editing and correction tools;
- materials, lighting and furniture; and
- mobile, VR and collaborative review.

Large structures are explicitly a future scope. Their inclusion in the vision does not mean the MVP should attempt to process an entire campus or hospital.

## 12. Assumptions and open questions

- The initial DXF subset will be selected after inspecting real sample drawings and consulting a domain reviewer.
- Numeric limits for file size, drawing extent, entity count, processing time and memory will be established by benchmarks.
- Whether door/window symbols can be recognised automatically depends on the supported drawing conventions.
- Required heights and other non-plan information may need user input or companion elevations/sections.
- Free hosting tiers are suitable for early demonstrations only; their resource, sleep, storage and usage limits must be checked at deployment time.
- The exact GLB export library and geometry-generation implementation will be selected through small technical prototypes.

## 13. Definition of done for the project

The portfolio project is ready to present when the MVP success criteria are demonstrated, core algorithms have automated tests, at least one benchmark report is documented, the repository can be set up from a clean checkout, and the developer can explain the major components and trade-offs without relying on Claude Code to speak on their behalf.
