import argparse
import json
import sys
from pathlib import Path

from api.engine.adapters.dxf.inspect import build_inventory
from api.engine.adapters.dxf.reader import read_dxf


def _positive_mm(text: str) -> float:
    v = float(text)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0 mm")
    return v


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="api")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect", help="DXF inventory as JSON")
    p.add_argument("dxf", type=Path)
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    p = sub.add_parser("interpret", help="DXF -> canonical model JSON")
    p.add_argument("dxf", type=Path)
    p.add_argument("--wall-height", type=_positive_mm, help="wall height in mm")
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args(argv)

    blocking = []
    if args.cmd == "inspect":
        text = json.dumps(build_inventory(args.dxf), indent=2) + "\n"
    else:
        project = read_dxf(args.dxf, args.wall_height)
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


if __name__ == "__main__":
    main()
