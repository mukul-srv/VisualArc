"""Stairs and ramps: flight outlines plus an arrow line each, read from their layers.

An outline is a closed axis-aligned rectangle. Its arrow is the one axis-aligned LINE lying inside
it, drawn from the bottom of the flight towards the top. No arrow, several arrows or an arrow that
fits no outline never gives a guessed direction: the flight is recorded without one and reported.
"""

from dataclasses import dataclass

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.settings import DEFAULTS, Settings

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class Outline:
    kind: str  # "stair" | "ramp"
    ref: SourceRef
    rect: Rect


@dataclass(frozen=True)
class Arrow:
    kind: str
    ref: SourceRef
    start: Point2
    end: Point2


@dataclass(frozen=True)
class Flight:
    id: str
    kind: str
    ref: SourceRef
    rect: Rect
    direction: str | None
    arrow: SourceRef | None

    @property
    def length(self) -> float | None:
        """Drawn extent along the direction (mm)."""
        if self.direction is None:
            return None
        x0, y0, x1, y1 = self.rect
        return x1 - x0 if self.direction[1] == "x" else y1 - y0


def _inside(rect: Rect, p: Point2, tol: float) -> bool:
    return rect[0] - tol <= p[0] <= rect[2] + tol and rect[1] - tol <= p[1] <= rect[3] + tol


def _direction(a: Arrow, tol: float) -> str | None:
    dx, dy = a.end[0] - a.start[0], a.end[1] - a.start[1]
    if abs(dy) <= tol < abs(dx):
        return "+x" if dx > 0 else "-x"
    if abs(dx) <= tol < abs(dy):
        return "+y" if dy > 0 else "-y"
    return None


def find_flights(
    outlines: list[Outline], arrows: list[Arrow], settings: Settings = DEFAULTS
) -> tuple[list[Flight], list[Issue]]:
    tol = settings.tolerance_mm
    flights, issues, used = [], [], set()
    counts: dict[str, int] = {}

    def within(o: Outline) -> list[Arrow]:
        return [
            a for a in arrows
            if a.kind == o.kind and _inside(o.rect, a.start, tol) and _inside(o.rect, a.end, tol)
        ]

    claims: dict[int, int] = {}  # arrow -> how many outlines contain it
    for o in outlines:
        for a in within(o):
            claims[id(a)] = claims.get(id(a), 0) + 1
    for o in sorted(outlines, key=lambda o: (o.kind, o.rect[1], o.rect[0])):
        mine = within(o)
        used.update(id(a) for a in mine)
        counts[o.kind] = n = counts.get(o.kind, 0) + 1
        fid, direction, arrow = f"{o.kind}-{n:03d}", None, None
        if len(mine) == 1 and claims[id(mine[0])] > 1:
            issues.append(Issue(
                code="stair_direction_ambiguous", severity="warning",
                message=f"{fid}: its arrow line {mine[0].ref.entity_handle} also lies inside "
                "another outline of the same kind (overlapping outlines); direction left unset",
                sources=[o.ref, mine[0].ref],
            ))
        elif len(mine) == 1 and (direction := _direction(mine[0], tol)) is not None:
            arrow = mine[0].ref
        elif len(mine) == 1:
            issues.append(Issue(
                code="stair_direction_unusable", severity="warning",
                message=f"{fid}: the arrow line {mine[0].ref.entity_handle} is not axis-aligned "
                "and non-degenerate; direction left unset",
                sources=[o.ref, mine[0].ref],
            ))
        elif mine:
            issues.append(Issue(
                code="stair_direction_ambiguous", severity="warning",
                message=f"{fid}: {len(mine)} arrow lines inside the outline; direction left unset",
                sources=[o.ref, *(a.ref for a in mine)],
            ))
        else:
            issues.append(Issue(
                code="stair_direction_missing", severity="warning",
                message=f"{fid} (outline {o.ref.entity_handle}) has no arrow line inside it, "
                "so its direction is unknown and no steps or slope are built; draw a line from "
                "the bottom of the flight towards the top",
                sources=[o.ref],
            ))
        flights.append(Flight(fid, o.kind, o.ref, o.rect, direction, arrow))
    lost = [a for a in arrows if id(a) not in used]
    if lost:
        cap = settings.unmapped_ref_cap
        issues.append(Issue(
            code="stair_arrow_orphan", severity="warning",
            message=f"{len(lost)} line(s) on a stair/ramp layer lie inside no outline of their "
            "kind and are not used",
            sources=[a.ref for a in lost[:cap]],
        ))
    return flights, issues
