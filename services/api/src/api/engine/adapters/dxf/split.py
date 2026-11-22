"""Floor candidates in one consolidated DXF (B8). Pure: no I/O beyond the ezdxf doc.

Two modes, chosen by the file:
1. layer prefix: some layer matches `settings.floor_prefix_pattern` (e.g. `L1|A-WALL`);
   group 1 is the floor key, the remainder is mapped by the normal layer rules.
2. spatial: wall/floor-boundary geometry grouped into clusters; two pieces closer than
   `settings.floor_gap_mm` (per axis) are one floor.
Everything that lands in no candidate (non-floor layers such as roofs and title
blocks, clusters without walls, entities far from every floor) is reported as a
`content_not_reconstructed` warning with source refs, never silently dropped.
Detection only proposes: the caller must have the user confirm each floor.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase

from ezdxf import bbox as ezbbox

from api.engine.canonical.model import Issue, SourceRef
from api.engine.settings import DEFAULTS, Settings

_ANCHOR_KINDS = ("LINE", "LWPOLYLINE")  # the geometry the reader builds walls/floors from


@dataclass(frozen=True)
class Candidate:
    key: str
    bbox: tuple[float, float, float, float]  # mm: minx, miny, maxx, maxy (walls + boundaries)
    entity_counts: dict[str, int]  # every entity assigned to this floor, by DXF type
    sources: list[SourceRef]  # wall/boundary entities, capped at unmapped_ref_cap
    handles: frozenset[str]  # every entity assigned to this floor

    def to_dict(self) -> dict:
        x0, y0, x1, y1 = self.bbox
        return {
            "key": self.key,
            "bbox": {"min": [x0, y0], "max": [x1, y1]},
            "entity_counts": dict(sorted(self.entity_counts.items())),
            # a proposal from the bbox min corner; provenance `inferred` until confirmed
            "proposed_offset": {"x": x0, "y": y0, "source": "inferred"},
            "sources": [s.model_dump(mode="json") for s in self.sources],
        }


@dataclass(frozen=True)
class Split:
    candidates: list[Candidate]
    issues: list[Issue]  # content_not_reconstructed warnings


@dataclass(frozen=True)
class FloorScope:
    """What read_dxf reads for one confirmed floor: only these entities, translated."""

    handles: frozenset[str]
    offset: tuple[float, float]  # mm; plan = source - offset
    notes: tuple[Issue, ...] = ()  # content_not_reconstructed, carried into the floor


def strip_floor_prefix(layer: str, settings: Settings = DEFAULTS) -> str:
    m = re.match(settings.floor_prefix_pattern, layer)
    return layer[m.end() :] if m else layer


def _natural(key: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", key)]


def _non_floor(layer: str, settings: Settings) -> bool:
    return any(fnmatchcase(layer.upper(), p) for p in settings.non_floor_layer_patterns)


def _box(e, k: float):
    ext = ezbbox.extents([e])
    if not ext.has_data:
        return None
    return (ext.extmin.x * k, ext.extmin.y * k, ext.extmax.x * k, ext.extmax.y * k)


def _union(boxes):
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _clusters(boxes: list, gap: float) -> list[list[int]]:
    """Indices grouped so that boxes within `gap` on both axes share a group
    (single linkage; sweep over min x so large drawings stay cheap)."""
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
    for n, i in enumerate(order):
        reach = boxes[i][2] + gap
        for j in order[n + 1 :]:
            if boxes[j][0] > reach:
                break
            if boxes[j][1] - boxes[i][3] <= gap and boxes[i][1] - boxes[j][3] <= gap:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(boxes)):
        groups[find(i)].append(i)
    return list(groups.values())


def _leftover_issues(left: dict[tuple[str, str], list], settings: Settings) -> list[Issue]:
    cap, out = settings.unmapped_ref_cap, []
    for (reason, layer), ents in sorted(left.items()):
        counts = ", ".join(f"{n} {t}" for t, n in sorted(Counter(e.dxftype() for e in ents).items()))
        more = f"; first {cap} of {len(ents)} listed" if len(ents) > cap else ""
        out.append(
            Issue(
                code="content_not_reconstructed",
                severity="warning",
                message=f"layer {layer}: {counts} not reconstructed ({reason}){more}",
                sources=[SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle) for e in ents[:cap]],
            )
        )
    return out


def excluded_issue(c: Candidate) -> Issue:
    """For a candidate the user chose not to build."""
    n = sum(c.entity_counts.values())
    return Issue(
        code="content_not_reconstructed",
        severity="warning",
        message=f"floor candidate {c.key} ({n} entities) was excluded by the user; not reconstructed",
        sources=c.sources,
    )


def detect_floors(doc, k: float, settings: Settings = DEFAULTS) -> Split:
    """`k` = drawing units -> mm. Candidates are sorted (natural key / left to right)."""
    wall_layers, floor_layers = settings.wall_layers, settings.floor_layers
    pattern = re.compile(settings.floor_prefix_pattern)
    ents = list(doc.modelspace())
    prefixed = any(pattern.match(e.dxf.layer) for e in ents)
    left: dict[tuple[str, str], list] = defaultdict(list)
    groups: dict[str, list] = defaultdict(list)  # candidate key -> entities (prefix mode)

    def mapped(e) -> str:
        return strip_floor_prefix(e.dxf.layer, settings).upper()

    def is_anchor(e) -> bool:
        return e.dxftype() in _ANCHOR_KINDS and (
            mapped(e) in wall_layers or mapped(e) in floor_layers
        )

    members: dict[str, list] = {}  # key -> entities
    if prefixed:
        for e in ents:
            m = pattern.match(e.dxf.layer)
            if _non_floor(mapped(e), settings):
                left[("non-floor layer", e.dxf.layer)].append(e)
            elif m is None:
                left[("not on a floor-prefixed layer", e.dxf.layer)].append(e)
            else:
                groups[m.group(1)].append(e)
        members = dict(groups)
    else:
        anchors, others = [], []
        for e in ents:
            if _non_floor(mapped(e), settings):
                left[("non-floor layer", e.dxf.layer)].append(e)
            elif is_anchor(e) and (b := _box(e, k)):
                anchors.append((e, b))
            else:
                others.append(e)
        clusters = _clusters([b for _, b in anchors], settings.floor_gap_mm)
        clusters.sort(key=lambda g: min((anchors[i][1][0], anchors[i][1][1]) for i in g))
        boxes = {}
        for g in clusters:
            es = [anchors[i][0] for i in g]
            if not any(mapped(e) in wall_layers for e in es):
                for e in es:
                    left[("cluster without walls", e.dxf.layer)].append(e)
                continue
            key = f"cluster-{len(members) + 1}"
            members[key] = es
            boxes[key] = _union([anchors[i][1] for i in g])
        half = settings.floor_gap_mm / 2  # candidates are > gap apart, so these never overlap
        for e in others:
            b = _box(e, k)
            cx, cy = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else (None, None)
            home = next(
                (
                    key
                    for key, (x0, y0, x1, y1) in boxes.items()
                    if b and x0 - half <= cx <= x1 + half and y0 - half <= cy <= y1 + half
                ),
                None,
            )
            if home:
                members[home].append(e)
            else:
                left[("outside every floor candidate", e.dxf.layer)].append(e)

    candidates = []
    for key in sorted(members, key=_natural):
        es = members[key]
        walls = [e for e in es if is_anchor(e) and mapped(e) in wall_layers]
        if not walls:  # prefix group with no wall geometry is not a floor
            for e in es:
                left[("cluster without walls", e.dxf.layer)].append(e)
            continue
        anchor = [(e, b) for e in es if is_anchor(e) and (b := _box(e, k))]
        candidates.append(
            Candidate(
                key=key,
                bbox=_union([b for _, b in anchor]),
                entity_counts=dict(Counter(e.dxftype() for e in es)),
                sources=[
                    SourceRef(layer=e.dxf.layer, entity_handle=e.dxf.handle)
                    for e, _ in anchor[: settings.unmapped_ref_cap]
                ],
                handles=frozenset(e.dxf.handle for e in es),
            )
        )
    return Split(candidates, _leftover_issues(left, settings))
