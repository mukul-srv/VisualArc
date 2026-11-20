---
type: log
---
# Learning Log

## 2026-11-19
- Repo skeleton created. Spec docs moved to `docs/project/`.
- Decision: walls in the first DXF convention are **paired boundary lines**, so thickness is read from the drawing. Cost: we need pairing and junction logic. See [[Project Map]].
- Open question: the convention for doors and windows (openings), to be decided at Fixture B.
- Wall pairing built (Task 5). Two parallel `A-WALL` lines 50–600 mm apart that overlap become one wall: the centreline is halfway between them, and the gap gives the thickness (`source_extracted`). If a line has partners at different offsets, that is a **blocking** issue, never a guess.
- Junctions: the wall lines are noded and turned into faces (`shapely.polygonize`). Faces that overlap wall rectangles count as wall material. Material minus the wall rectangles leaves the corner and T gaps. These become `Junction` pieces with provenance `inferred`, because the drawing never states them.
- GLB export built (Task 7). The only coordinate conversion lives in the exporter: mm → m and plan (x, y, z_up) → glTF (x, z_up, −y) (ADR-001). That swap is a pure rotation (determinant +1), so triangle winding and normals survive; a mirror (det −1) would turn every mesh inside-out. Tests check this via positive volume and floor normals pointing +Y.
- Metadata: each element is a glTF node named by its canonical id; provenance and source handles ride as mesh `extras`. A sidecar `<stem>.meta.json` repeats them with bounds and watertightness, so verification doesn't depend on any one tool keeping extras.
