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
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.settings import DEFAULTS


def _positive_mm(text: str) -> float:
    v = float(text)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0 mm")
    return v


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
    p.add_argument(
        "--units",
        choices=list(USER_UNITS),
        help="drawing units; required if the DXF has no $INSUNITS, error if it conflicts",
    )
    p.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)

    if args.cmd == "build":
        _build(args)
        return

    blocking = []
    if args.cmd == "inspect":
        text = json.dumps(build_inventory(args.dxf, args.max_bytes), indent=2) + "\n"
    else:
        project = read_dxf(args.dxf, args.wall_height, args.max_bytes, args.units)
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
    project = read_dxf(args.dxf, args.wall_height, args.max_bytes, args.units)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.dxf.stem
    # canonical JSON always written: it is the evidence for why a build was blocked
    (args.out / f"{stem}.canonical.json").write_text(
        project.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    _exit_if_blocking([i for i in project.issues if i.severity == "blocking"])
    scene = build_scene(project)
    (args.out / f"{stem}.glb").write_bytes(scene.export(file_type="glb"))
    (args.out / f"{stem}.meta.json").write_text(
        json.dumps(build_meta(project, scene), indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {stem}.canonical.json, {stem}.glb, {stem}.meta.json to {args.out}")


if __name__ == "__main__":
    main()
