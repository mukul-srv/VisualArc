# Verification report: fixture_openings

- Source file: `fixture_openings.dxf`
- Schema version: 0.10.0
- Units: mm
- Result: **OK** (0 blocking, 7 warnings)

## Blocking issues

None.

## Warnings

- `opening_symbol_ignored`: opening layer A-DOOR: ignored decorative 3 ARC, 3 LINE (swings, leaves, glass, tags are never geometry) (sources: A-DOOR:5E, A-DOOR:5F, A-DOOR:60, A-DOOR:61, A-DOOR:62, A-DOOR:63)
- `opening_dimension_defaulted`: 3 door opening(s): height 2100 mm, sill 0 mm from provisional Settings defaults (not in the DXF) (sources: A-DOOR:55, A-DOOR:56, A-DOOR:5D)
- `opening_dimension_defaulted`: 4 window opening(s): height 1200 mm, sill 900 mm from provisional Settings defaults (not in the DXF) (sources: A-GLAZ:51, A-GLAZ:54, A-GLAZ:59, A-GLAZ:5A)
- `elevation_defaulted`: floor elevation assumed 0 mm; DXF plan carries no elevation (sources: -)
- `wall_role_inferred`: 10 wall(s) have no role layer (A-WALL-EXTR, A-WALL-INTR); role inferred from geometry (a face on the outer boundary of all walls = exterior). Walls around an interior courtyard read as interior. (sources: A-WALL:33, A-WALL:37, A-WALL:34, A-WALL:38, A-WALL:39, A-WALL:35, A-WALL:3A, A-WALL:3B, A-WALL:36, A-WALL:3C, A-WALL:41, A-WALL:43, A-WALL:42, A-WALL:44, A-WALL:49, A-WALL:4B, A-WALL:4A, A-WALL:4C, A-WALL:4D, A-WALL:4F, A-WALL:4E, A-WALL:50, A-WALL:45, A-WALL:47, A-WALL:46, A-WALL:48, A-WALL:3D, A-WALL:40, A-WALL:3E, A-WALL:3F)
- `room_name_defaulted`: no label inside Room 1, Room 2, Room 3; numbered names assumed (sources: -)
- `roof_type_unknown`: no roof type (choose a building type or set the parameter); no roof built (sources: -)

## Values by provenance

| Provenance | Count |
| --- | --- |
| source_extracted | 24 |
| user_provided | 10 |
| defaulted | 15 |
| inferred | 0 |

Junctions (8) are always `inferred`: corner/T fill between paired-line walls, not drawn in the source.

## Assumptions: user-provided, defaulted and inferred values

| Element | Field | Value (mm) | Provenance | Sources |
| --- | --- | --- | --- | --- |
| floor-0 | elevation | 0 | defaulted | - |
| wall-001 | height | 3000 | user_provided | A-WALL:33, A-WALL:37, A-WALL:34, A-WALL:38 |
| wall-002 | height | 3000 | user_provided | A-WALL:34, A-WALL:39, A-WALL:35, A-WALL:3A |
| wall-003 | height | 3000 | user_provided | A-WALL:35, A-WALL:3B, A-WALL:36, A-WALL:3C |
| wall-004 | height | 3000 | user_provided | A-WALL:41, A-WALL:43, A-WALL:42, A-WALL:44 |
| wall-005 | height | 3000 | user_provided | A-WALL:49, A-WALL:4B, A-WALL:4A, A-WALL:4C |
| wall-006 | height | 3000 | user_provided | A-WALL:4D, A-WALL:4F, A-WALL:4E, A-WALL:50 |
| wall-007 | height | 3000 | user_provided | A-WALL:45, A-WALL:47, A-WALL:46, A-WALL:48 |
| wall-008 | height | 3000 | user_provided | A-WALL:3D, A-WALL:40 |
| wall-009 | height | 3000 | user_provided | A-WALL:3E, A-WALL:40 |
| wall-010 | height | 3000 | user_provided | A-WALL:3F, A-WALL:40 |
| opening-001 | height | 1200 | defaulted | A-GLAZ:51, A-WALL:52, A-WALL:53 |
| opening-001 | sill_height | 900 | defaulted | A-GLAZ:51, A-WALL:52, A-WALL:53 |
| opening-002 | height | 1200 | defaulted | A-GLAZ:54 |
| opening-002 | sill_height | 900 | defaulted | A-GLAZ:54 |
| opening-003 | height | 2100 | defaulted | A-DOOR:55 |
| opening-003 | sill_height | 0 | defaulted | A-DOOR:55 |
| opening-004 | height | 2100 | defaulted | A-DOOR:56, A-WALL:57, A-WALL:58 |
| opening-004 | sill_height | 0 | defaulted | A-DOOR:56, A-WALL:57, A-WALL:58 |
| opening-005 | height | 1200 | defaulted | A-GLAZ:59 |
| opening-005 | sill_height | 900 | defaulted | A-GLAZ:59 |
| opening-006 | height | 1200 | defaulted | A-GLAZ:5A, A-WALL:5B, A-WALL:5C |
| opening-006 | sill_height | 900 | defaulted | A-GLAZ:5A, A-WALL:5B, A-WALL:5C |
| opening-007 | height | 2100 | defaulted | A-DOOR:5D |
| opening-007 | sill_height | 0 | defaulted | A-DOOR:5D |

## Generated key dimensions

- Footprint (wall extents): 9600 x 4000 mm
- Wall heights: 3000 mm
- Walls: 10
- Junctions: 8
- Floor boundaries: 3
- Slabs: 0
- Rooms: 3
- Columns: 0
- Balconies: 0
- Stairs: 0
- Ramps: 0
- Roofs: 0
- Openings: 7

## Expected versus generated

| Quantity | Expected | Generated | Match |
| --- | --- | --- | --- |
| Footprint (mm) | 9600 x 4000 | 9600 x 4000 | yes |
| walls | 10 | 10 | yes |
| junctions | 8 | 8 | yes |
| floor boundaries | 3 | 3 | yes |
| slabs | 0 | 0 | yes |
| rooms | 3 | 3 | yes |
| columns | 0 | 0 | yes |
| balconies | 0 | 0 | yes |
| stairs | 0 | 0 | yes |
| ramps | 0 | 0 | yes |
| roofs | 0 | 0 | yes |
| openings | 7 | 7 | yes |
| Wall heights (mm) | 3000 | 3000 | yes |

## Elements and source references

| Element | Kind | Sources |
| --- | --- | --- |
| wall-001 | wall | A-WALL:33, A-WALL:37, A-WALL:34, A-WALL:38 |
| wall-002 | wall | A-WALL:34, A-WALL:39, A-WALL:35, A-WALL:3A |
| wall-003 | wall | A-WALL:35, A-WALL:3B, A-WALL:36, A-WALL:3C |
| wall-004 | wall | A-WALL:41, A-WALL:43, A-WALL:42, A-WALL:44 |
| wall-005 | wall | A-WALL:49, A-WALL:4B, A-WALL:4A, A-WALL:4C |
| wall-006 | wall | A-WALL:4D, A-WALL:4F, A-WALL:4E, A-WALL:50 |
| wall-007 | wall | A-WALL:45, A-WALL:47, A-WALL:46, A-WALL:48 |
| wall-008 | wall | A-WALL:3D, A-WALL:40 |
| wall-009 | wall | A-WALL:3E, A-WALL:40 |
| wall-010 | wall | A-WALL:3F, A-WALL:40 |
| opening-001 | window in wall-001 | A-GLAZ:51, A-WALL:52, A-WALL:53 |
| opening-002 | window in wall-002 | A-GLAZ:54 |
| opening-003 | door in wall-003 | A-DOOR:55 |
| opening-004 | door in wall-005 | A-DOOR:56, A-WALL:57, A-WALL:58 |
| opening-005 | window in wall-004 | A-GLAZ:59 |
| opening-006 | window in wall-007 | A-GLAZ:5A, A-WALL:5B, A-WALL:5C |
| opening-007 | door in wall-006 | A-DOOR:5D |
| fb-001 | floor boundary | A-FLOR:64 |
| fb-002 | floor boundary | A-FLOR:65 |
| fb-003 | floor boundary | A-FLOR:66 |

## Limitations

- Supported input: restricted DXF convention (Document 08); anything else is listed under Warnings, never guessed.
- Unresolved regions and ignored geometry appear above as issues; absence of an issue is not proof the drawing has none outside the convention.
- This report restates the canonical model; it does not replace visual inspection of the 3D model.
