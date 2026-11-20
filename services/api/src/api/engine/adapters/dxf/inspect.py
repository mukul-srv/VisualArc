"""DXF inventory: what is in the file, before any interpretation."""

from collections import Counter, defaultdict
from pathlib import Path

from ezdxf import bbox

from api.engine.adapters.dxf.reader import _unit_label, load_doc
from api.engine.settings import DEFAULTS


def build_inventory(path: Path, max_bytes: int = DEFAULTS.max_dxf_bytes) -> dict:
    doc = load_doc(path, max_bytes)
    msp = doc.modelspace()
    insunits = doc.header.get("$INSUNITS", 0)

    counts: Counter[str] = Counter()
    handles: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for e in msp:
        layer, kind = e.dxf.layer, e.dxftype()
        counts[kind] += 1
        handles[layer][kind].append(e.dxf.handle)

    ext = bbox.extents(msp)
    return {
        "source": path.name,
        "dxf_version": doc.dxfversion,
        "units": {
            "insunits": insunits,
            # 0 = unitless: caller must supply units, never assume. Unlisted codes
            # are described as "unknown" (inventory never blocks).
            "name": _unit_label(insunits) if insunits else None,
        },
        "layers": sorted(layer.dxf.name for layer in doc.layers),
        "entity_counts": dict(sorted(counts.items())),
        "entities_by_layer": {
            layer: {kind: hs for kind, hs in sorted(kinds.items())}
            for layer, kinds in sorted(handles.items())
        },
        "extents": (
            {"min": list(ext.extmin), "max": list(ext.extmax)} if ext.has_data else None
        ),
    }
