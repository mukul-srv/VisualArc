"""Canonical project -> human-readable Markdown verification report (T14).

Pure function of the canonical model (plus an optional expected model), so the
report is deterministic and snapshot-testable. It adds no interpretation: every
number is read from the model. Values are mm, the canonical unit (ADR-001).
"""

from collections import Counter
from collections.abc import Iterator

from api.engine.canonical.model import Measured, Project, SourceRef


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _refs(sources: list[SourceRef]) -> str:
    return ", ".join(f"{s.layer}:{s.entity_handle}" for s in sources) or "-"


def _measured(project: Project) -> Iterator[tuple[str, str, Measured, list[SourceRef]]]:
    """(element id, field, value, sources) for every Measured in the model."""
    for b in project.buildings:
        for f in b.floors:
            yield f.id, "elevation", f.elevation, []
            for w in f.walls:
                yield w.id, "thickness", w.thickness, w.sources
                if w.height is not None:
                    yield w.id, "height", w.height, w.sources
            for sl in f.slabs:
                yield sl.id, "thickness", sl.thickness, sl.sources
            for o in f.openings:
                for name in ("offset", "width", "height", "sill_height"):
                    yield o.id, name, getattr(o, name), o.sources


def _footprint(project: Project) -> tuple[float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for b in project.buildings:
        for f in b.floors:
            for w in f.walls:
                h = w.thickness.value / 2
                (x0, y0), (x1, y1) = w.centreline.start, w.centreline.end
                # thickness extends perpendicular to the centreline
                hx, hy = (0, h) if abs(x1 - x0) >= abs(y1 - y0) else (h, 0)
                xs += [x0 - hx, x1 + hx, x0 + hx, x1 - hx]
                ys += [y0 - hy, y1 + hy, y0 + hy, y1 - hy]
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs else None


def _counts(project: Project) -> dict[str, int]:
    floors = [f for b in project.buildings for f in b.floors]
    return {
        "walls": sum(len(f.walls) for f in floors),
        "junctions": sum(len(f.junctions) for f in floors),
        "floor boundaries": sum(len(f.boundaries) for f in floors),
        "slabs": sum(len(f.slabs) for f in floors),
        "rooms": sum(len(f.rooms) for f in floors),
        "openings": sum(len(f.openings) for f in floors),
    }


def _wall_heights(project: Project) -> str:
    hs = sorted(
        {
            w.height.value
            for b in project.buildings
            for f in b.floors
            for w in f.walls
            if w.height
        }
    )
    return ", ".join(_num(h) for h in hs) or "-"


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def build_report(project: Project, expected: Project | None = None) -> str:
    issues = project.issues
    blocking = [i for i in issues if i.severity == "blocking"]
    warnings = [i for i in issues if i.severity == "warning"]
    out = [f"# Verification report: {project.id}", ""]
    out += [
        f"- Source file: `{project.source_file}`",
        f"- Schema version: {project.schema_version}",
        f"- Units: {project.units}",
        (
            f"- Result: **{'BLOCKED' if blocking else 'OK'}** "
            f"({len(blocking)} blocking, {len(warnings)} warnings)"
        ),
        "",
    ]

    for title, items in (("Blocking issues", blocking), ("Warnings", warnings)):
        out += [f"## {title}", ""]
        out += [
            f"- `{i.code}`: {i.message} (sources: {_refs(i.sources)})" for i in items
        ] or ["None."]
        out.append("")

    rows = list(_measured(project))
    out += ["## Values by provenance", ""]
    tally = Counter(m.source for _, _, m, _ in rows)
    out += [_row("Provenance", "Count"), _row("---", "---")]
    for p in ("source_extracted", "user_provided", "defaulted", "inferred"):
        out.append(_row(p, str(tally.get(p, 0))))
    n_junc = sum(len(f.junctions) for b in project.buildings for f in b.floors)
    out += [
        "",
        (
            f"Junctions ({n_junc}) are always `inferred`: corner/T fill between "
            "paired-line walls, not drawn in the source."
        ),
        "",
        "## Assumptions: user-provided, defaulted and inferred values",
        "",
    ]
    flagged = [r for r in rows if r[2].source != "source_extracted"]
    if flagged:
        out += [
            _row("Element", "Field", "Value (mm)", "Provenance", "Sources"),
            _row(*["---"] * 5),
        ]
        for eid, name, m, srcs in flagged:
            out.append(_row(eid, name, _num(m.value), m.source, _refs(srcs)))
    else:
        out.append("None: every measured value was extracted from the drawing.")
    out.append("")

    out += ["## Generated key dimensions", ""]
    fp = _footprint(project)
    out.append(
        f"- Footprint (wall extents): {_num(fp[0])} x {_num(fp[1])} mm"
        if fp
        else "- Footprint: no walls generated"
    )
    out.append(f"- Wall heights: {_wall_heights(project)} mm")
    out += [f"- {k.capitalize()}: {v}" for k, v in _counts(project).items()]
    out.append("")

    if expected is not None:
        out += ["## Expected versus generated", ""]
        out += [_row("Quantity", "Expected", "Generated", "Match"), _row(*["---"] * 4)]
        pairs = [("Footprint (mm)", _fmt_fp(_footprint(expected)), _fmt_fp(fp))]
        pairs += [
            (k, str(v), str(_counts(project)[k])) for k, v in _counts(expected).items()
        ]
        pairs.append(
            ("Wall heights (mm)", _wall_heights(expected), _wall_heights(project))
        )
        for name, e, g in pairs:
            out.append(_row(name, e, g, "yes" if e == g else "**NO**"))
        out.append("")

    out += ["## Elements and source references", ""]
    out += [_row("Element", "Kind", "Sources"), _row("---", "---", "---")]
    for b in project.buildings:
        for f in b.floors:
            for w in f.walls:
                out.append(_row(w.id, "wall", _refs(w.sources)))
            for o in f.openings:
                out.append(_row(o.id, f"{o.kind} in {o.wall_id}", _refs(o.sources)))
            for fb in f.boundaries:
                out.append(_row(fb.id, "floor boundary", _refs(fb.sources)))
    out += [
        "",
        "## Limitations",
        "",
        (
            "- Supported input: restricted DXF convention (Document 08); anything else "
            "is listed under Warnings, never guessed."
        ),
        (
            "- Unresolved regions and ignored geometry appear above as issues; "
            "absence of an issue is not proof the drawing has none outside the convention."
        ),
        (
            "- This report restates the canonical model; it does not replace visual "
            "inspection of the 3D model."
        ),
        "",
    ]
    return "\n".join(out)


def _fmt_fp(fp: tuple[float, float] | None) -> str:
    return f"{_num(fp[0])} x {_num(fp[1])}" if fp else "-"
