import argparse
import json
import sys
from pathlib import Path

from api.engine.adapters.dxf.inspect import build_inventory
from api.engine.adapters.dxf.reader import (
    USER_UNITS,
    InputError,
    read_dxf,
)
from api.engine.canonical.model import Project
from api.engine.settings import DEFAULTS
from api.pipeline import write_artifacts


def _positive_mm(text: str) -> float:
    v = float(text)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0 mm")
    return v


def _nonneg_mm(text: str) -> float:
    v = float(text)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0 mm")
    return v


def _opening_flags(p) -> None:
    p.add_argument("--ceiling-height", type=_positive_mm, help="ceiling height in mm")
    # ADR-002 §5: one value per kind; omitted -> Settings default, `defaulted`
    p.add_argument("--door-height", type=_positive_mm, help="door height in mm")
    p.add_argument("--window-height", type=_positive_mm, help="window height in mm")
    p.add_argument(
        "--window-sill", type=_nonneg_mm, help="window sill above floor in mm"
    )


def _read(args):
    return read_dxf(
        args.dxf,
        args.wall_height,
        args.max_bytes,
        args.units,
        door_height=args.door_height,
        window_height=args.window_height,
        window_sill=args.window_sill,
        ceiling_height=args.ceiling_height,
    )


def _max_bytes(text: str) -> int:
    v = float(text)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0 MB")
    return int(v * 2**20)


def main(argv: list[str] | None = None) -> None:
    try:
        _main(argv)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(3)  # 0 ok, 1 blocking issues, 2 usage, 3 rejected input


def _main(argv: list[str] | None) -> None:
    parser = argparse.ArgumentParser(prog="api")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-projects", help="import legacy project.json files into the DB")
    p.add_argument("--owner", metavar="EMAIL", help="account that owns the imported projects")
    p = sub.add_parser("inspect", help="DXF inventory as JSON")
    p.add_argument("dxf", type=Path)
    p.add_argument(
        "--max-mb",
        dest="max_bytes",
        type=_max_bytes,
        default=DEFAULTS.max_dxf_bytes,
        help="input size limit in MB (provisional default 50)",
    )
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    p = sub.add_parser("interpret", help="DXF -> canonical model JSON")
    p.add_argument("dxf", type=Path)
    p.add_argument(
        "--max-mb",
        dest="max_bytes",
        type=_max_bytes,
        default=DEFAULTS.max_dxf_bytes,
        help="input size limit in MB (provisional default 50)",
    )
    p.add_argument("--wall-height", type=_positive_mm, help="wall height in mm")
    _opening_flags(p)
    p.add_argument(
        "--units",
        choices=list(USER_UNITS),
        help="drawing units; required if the DXF has no $INSUNITS, error if it conflicts",
    )
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    p = sub.add_parser("build", help="DXF -> canonical JSON + GLB + meta report")
    p.add_argument("dxf", type=Path)
    p.add_argument(
        "--max-mb",
        dest="max_bytes",
        type=_max_bytes,
        default=DEFAULTS.max_dxf_bytes,
        help="input size limit in MB (provisional default 50)",
    )
    p.add_argument("--wall-height", type=_positive_mm, help="wall height in mm")
    _opening_flags(p)
    p.add_argument(
        "--units",
        choices=list(USER_UNITS),
        help="drawing units; required if the DXF has no $INSUNITS, error if it conflicts",
    )
    p.add_argument("--out", type=Path, required=True, help="output directory")
    p.add_argument(
        "--expected",
        type=Path,
        help="expected canonical JSON; adds an expected-vs-generated table to the report",
    )
    args = parser.parse_args(argv)

    if args.cmd == "import-projects":
        from api.importer import import_projects

        try:
            imported, skipped = import_projects(args.owner)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(2)
        print(f"imported {imported}, skipped {skipped}")
        return
    if args.cmd == "build":
        _build(args)
        return

    blocking = []
    if args.cmd == "inspect":
        text = json.dumps(build_inventory(args.dxf, args.max_bytes), indent=2) + "\n"
    else:
        project = _read(args)
        text = project.model_dump_json(indent=2) + "\n"
        blocking = [i for i in project.issues if i.severity == "blocking"]

    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    _exit_if_blocking(blocking)


def _exit_if_blocking(blocking) -> None:
    if blocking:
        for i in blocking:
            print(f"blocking: {i.code}: {i.message}", file=sys.stderr)
        sys.exit(1)


def _build(args) -> None:
    project = _read(args)
    expected = (
        Project.model_validate_json(args.expected.read_text(encoding="utf-8"))
        if args.expected
        else None
    )
    names = write_artifacts(project, args.out, args.dxf.stem, expected)
    _exit_if_blocking([i for i in project.issues if i.severity == "blocking"])
    print(f"wrote {', '.join(sorted(names))} to {args.out}")


if __name__ == "__main__":
    main()
