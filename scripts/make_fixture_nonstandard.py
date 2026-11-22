"""Generate Fixture Nonstandard: Fixture Openings with non-standard layer names (conventions, 06).

Run: cd services/api && uv run python ../../scripts/make_fixture_nonstandard.py

Same geometry as `fixture_openings.dxf` (run `make_fixture_openings.py` first); only the layers are
renamed: A-WALL -> WALLS, A-FLOR -> ROOMS, A-DOOR -> DOORS, A-GLAZ -> WINDOWS. With the default AIA
conventions every entity is an unmapped layer and no wall is found; after mapping those four layers
(wall / floor / door / window) it must generate exactly like fixture_openings.
"""

from pathlib import Path

import ezdxf

INPUT = Path(__file__).resolve().parents[1] / "fixtures" / "input"
RENAME = {"A-WALL": "WALLS", "A-FLOR": "ROOMS", "A-DOOR": "DOORS", "A-GLAZ": "WINDOWS"}


def main() -> None:
    doc = ezdxf.readfile(INPUT / "fixture_openings.dxf")
    for e in doc.modelspace():
        e.dxf.layer = RENAME.get(e.dxf.layer, e.dxf.layer)
    for old, new in RENAME.items():
        doc.layers.add(new)
        doc.layers.remove(old)
    out = INPUT / "fixture_nonstandard.dxf"
    doc.saveas(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
