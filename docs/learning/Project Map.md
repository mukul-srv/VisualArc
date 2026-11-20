---
type: map
---
# Project Map

```
DXF file
  -> adapters/dxf   (inventory, read entities, keep handles)
  -> canonical      (Project/Building/Floor/Wall, mm, provenance)
  -> validation     (blocking errors vs warnings)
  -> geometry2d     (pair wall lines, fill junctions)
  -> geometry3d     (extrude walls, floor slab)
  -> exporters/glb  (mm -> m, Y-up)  + model.meta.json
  -> apps/web viewer (Three.js)
```

Built so far: `services/api` FastAPI `/health`; `apps/web` Next.js starter. Engine modules not created yet.

Key decision: [[ADR-001-units-coordinates]].
