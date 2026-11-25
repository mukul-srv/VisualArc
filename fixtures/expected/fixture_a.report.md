# Verification report: fixture_a

- Source file: `fixture_a.dxf`
- Schema version: 0.11.0
- Units: mm
- Result: **OK** (0 blocking, 4 warnings)

## Blocking issues

None.

## Warnings

- `elevation_defaulted`: floor elevation assumed 0 mm; DXF plan carries no elevation (sources: -)
- `wall_role_inferred`: 7 wall(s) have no role layer (A-WALL-EXTR, A-WALL-INTR); role inferred from geometry (a face on the outer boundary of all walls = exterior). Walls around an interior courtyard read as interior. (sources: A-WALL:31, A-WALL:35, A-WALL:36, A-WALL:34, A-WALL:3A, A-WALL:3B, A-WALL:3C, A-WALL:37, A-WALL:32, A-WALL:39, A-WALL:33, A-WALL:38)
- `room_name_defaulted`: no label inside Room 1, Room 2; numbered names assumed (sources: -)
- `roof_type_unknown`: no roof type (choose a building type or set the parameter); no roof built (sources: -)

## Values by provenance

| Provenance | Count |
| --- | --- |
| source_extracted | 7 |
| user_provided | 7 |
| defaulted | 1 |
| inferred | 0 |

Junctions (6) are always `inferred`: corner/T fill between paired-line walls, not drawn in the source.

## Assumptions: user-provided, defaulted and inferred values

| Element | Field | Value (mm) | Provenance | Sources |
| --- | --- | --- | --- | --- |
| floor-0 | elevation | 0 | defaulted | - |
| wall-001 | height | 3000 | user_provided | A-WALL:31, A-WALL:35 |
| wall-002 | height | 3000 | user_provided | A-WALL:31, A-WALL:36 |
| wall-003 | height | 3000 | user_provided | A-WALL:34, A-WALL:3A |
| wall-004 | height | 3000 | user_provided | A-WALL:3B, A-WALL:3C |
| wall-005 | height | 3000 | user_provided | A-WALL:37, A-WALL:32 |
| wall-006 | height | 3000 | user_provided | A-WALL:39, A-WALL:33 |
| wall-007 | height | 3000 | user_provided | A-WALL:38, A-WALL:33 |

## Generated key dimensions

- Footprint (wall extents): 8200 x 5200 mm
- Wall heights: 3000 mm
- Walls: 7
- Junctions: 6
- Floor boundaries: 2
- Slabs: 0
- Rooms: 2
- Columns: 0
- Balconies: 0
- Stairs: 0
- Ramps: 0
- Roofs: 0
- Openings: 0

## Expected versus generated

| Quantity | Expected | Generated | Match |
| --- | --- | --- | --- |
| Footprint (mm) | 8200 x 5200 | 8200 x 5200 | yes |
| walls | 7 | 7 | yes |
| junctions | 6 | 6 | yes |
| floor boundaries | 2 | 2 | yes |
| slabs | 0 | 0 | yes |
| rooms | 2 | 2 | yes |
| columns | 0 | 0 | yes |
| balconies | 0 | 0 | yes |
| stairs | 0 | 0 | yes |
| ramps | 0 | 0 | yes |
| roofs | 0 | 0 | yes |
| openings | 0 | 0 | yes |
| Wall heights (mm) | 3000 | 3000 | yes |

## Elements and source references

| Element | Kind | Sources |
| --- | --- | --- |
| wall-001 | wall | A-WALL:31, A-WALL:35 |
| wall-002 | wall | A-WALL:31, A-WALL:36 |
| wall-003 | wall | A-WALL:34, A-WALL:3A |
| wall-004 | wall | A-WALL:3B, A-WALL:3C |
| wall-005 | wall | A-WALL:37, A-WALL:32 |
| wall-006 | wall | A-WALL:39, A-WALL:33 |
| wall-007 | wall | A-WALL:38, A-WALL:33 |
| fb-001 | floor boundary | A-FLOR:3D |
| fb-002 | floor boundary | A-FLOR:3E |

## Limitations

- Supported input: restricted DXF convention (Document 08); anything else is listed under Warnings, never guessed.
- Unresolved regions and ignored geometry appear above as issues; absence of an issue is not proof the drawing has none outside the convention.
- This report restates the canonical model; it does not replace visual inspection of the 3D model.
