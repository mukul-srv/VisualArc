"""Build apps/web/public/world.svg (offline location picker) from Natural Earth 110m land (public domain).

Usage: python scripts/make_world_map.py ne_110m_land.geojson
Equirectangular: x = lon + 180, y = 90 - lat (viewBox 0 0 360 180), so a click maps back to lon/lat directly.
"""

import json
import sys
from pathlib import Path

gj = json.loads(Path(sys.argv[1]).read_text("utf-8"))
d = []
for f in gj["features"]:
    g = f["geometry"]
    for poly in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]:
        for ring in poly:
            d.append("M" + "L".join(f"{lon + 180:.1f} {90 - lat:.1f}" for lon, lat in ring) + "Z")
out = Path(__file__).resolve().parents[1] / "apps/web/public/world.svg"
out.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 180"><rect width="360" height="180" fill="#1e2a38"/>'
               f'<path d="{"".join(d)}" fill="#4a5d4a" stroke="#6f8a6f" stroke-width="0.2"/></svg>\n', "utf-8")
print(out, out.stat().st_size)
