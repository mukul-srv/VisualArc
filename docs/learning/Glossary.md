---
type: glossary
---
# Glossary

- **DXF**: Drawing Exchange Format, AutoCAD's text/binary exchange format of entities (LINE, LWPOLYLINE, INSERT…) on named layers.
- **Entity handle**: hex ID unique within a DXF file. We store it as the source reference.
- **$INSUNITS**: DXF header variable giving drawing units (4 = mm, 6 = m).
- **Paired boundary lines**: a wall drawn as two parallel lines. The gap between them is the wall thickness.
- **Provenance**: where a value came from: source_extracted, user_provided, defaulted or inferred.
- **Canonical model**: the format-independent internal building representation. Every adapter produces it.
- **GLB**: binary glTF, a 3D scene format in metres, Y-up.
