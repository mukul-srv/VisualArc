"""Floor boundary validity: a floor we cannot trust is blocking, never repaired."""

from shapely.geometry import Polygon
from shapely.validation import explain_validity

from api.engine.canonical.model import Issue, Point2, SourceRef
from api.engine.settings import DEFAULTS, Settings


def floor_issue(
    pts: list[Point2], ref: SourceRef, settings: Settings = DEFAULTS
) -> Issue | None:
    """Blocking issue if the ring self-intersects or has no area; winding is irrelevant."""
    poly = Polygon(pts)
    if poly.is_valid and poly.area > settings.tolerance_mm:
        return None
    reason = (
        explain_validity(poly)
        if not poly.is_valid
        else f"area {poly.area:.3f} mm2 is not positive"
    )
    return Issue(
        code="invalid_floor_boundary",
        severity="blocking",
        message=f"floor polyline {ref.entity_handle} is not a valid polygon "
        f"({reason}); excluded",
        sources=[ref],
    )
