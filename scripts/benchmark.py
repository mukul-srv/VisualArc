"""T21 benchmark: time, peak memory and correctness of the DXF -> GLB pipeline.

Run (from services/api):
    uv run python ../../scripts/benchmark.py [--repeats 3] [--out DIR] [--max-seconds 600]

What it measures (each run is a FRESH subprocess so peak memory is per run):
  entity scale   Fixture D k x k tiles, k = 1..12 (stops once a run exceeds --max-seconds
                 or fails; sizes slower than 60 s are run once); counts must equal N x per-tile counts.
  extent probe   one tile translated by 0 .. 1e8 mm; geometry must be unchanged.
Per run: input bytes, entity counts, stage timings (parse, interpret, geometry3d,
GLB export, meta, report, canonical JSON), total, peak working set, GLB size, issue
counts, element counts vs expected, wall-thickness exactness, watertightness.
"interpret" includes pydantic validation (not separable). Timings are wall clock
(time.perf_counter); peak memory is the OS peak working set of the child process.
Nothing here is a limit: limits are chosen from the results (docs, MC-8).
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TILE_COUNTS = [(k, k) for k in (1, 2, 3, 4, 5, 6, 7, 8, 10, 12)]
SLOW_S = 60  # a size whose first run exceeds this is measured once (time budget)
OFFSETS = [0, 1e5, 1e6, 1e7, 1e8]  # mm
PER_TILE = {"walls": 10, "junctions": 8, "floor boundaries": 3, "openings": 7}


def peak_rss_bytes() -> int | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        f = ctypes.windll.psapi.GetProcessMemoryInfo
        f.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        ok = f(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return int(pmc.PeakWorkingSetSize) if ok else None
    import resource

    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r if sys.platform == "darwin" else r * 1024


def child(dxf: Path, expect_tiles: int) -> dict:
    """One measured pipeline run in this process."""
    import dataclasses
    from collections import Counter

    from api.engine.adapters.dxf.reader import load_doc, read_dxf
    from api.engine.exporters.glb import build_meta, build_scene
    from api.engine.exporters.report import build_report
    from api.engine.settings import DEFAULTS

    if os.environ.get("BENCH_NO_PLUGS"):
        # DIAGNOSTIC ONLY: disables the O(W^3) gap_closed_by_jamb_pair check to expose
        # the next bottleneck. Output of such a run is not a valid interpretation.
        import api.engine.geometry2d.openings as _o

        _o._plugs = lambda walls, tol: []

    t = {}
    clock = time.perf_counter

    s = clock()
    doc = load_doc(dxf, 10**9)
    t["parse"] = clock() - s
    kinds = Counter(e.dxftype() for e in doc.modelspace())
    del doc

    s = clock()
    # the benchmark deliberately runs ABOVE the enforced limits (they exist because of it)
    big = 10**9
    uncapped = dataclasses.replace(
        DEFAULTS,
        max_dxf_bytes=big,
        max_entities=big,
        max_wall_segments=big,
        max_opening_markers=big,
    )
    project = read_dxf(dxf, 3000, settings=uncapped)
    t["read_total"] = clock() - s
    t["interpret"] = t["read_total"] - t["parse"]  # read_dxf re-parses internally

    s = clock()
    scene = build_scene(project)
    t["geometry3d"] = clock() - s
    s = clock()
    glb = scene.export(file_type="glb")
    t["glb_export"] = clock() - s
    s = clock()
    meta = build_meta(project, scene)
    t["meta"] = clock() - s
    s = clock()
    report = build_report(project)
    t["report"] = clock() - s
    s = clock()
    canonical = project.model_dump_json()
    t["canonical_json"] = clock() - s
    t["total"] = (
        t["read_total"] + t["geometry3d"] + t["glb_export"] + t["meta"] + t["report"]
    )

    floor = project.buildings[0].floors[0]
    counts = {
        "walls": len(floor.walls),
        "junctions": len(floor.junctions),
        "floor boundaries": len(floor.boundaries),
        "openings": len(floor.openings),
    }
    expected = {k: v * expect_tiles for k, v in PER_TILE.items()}
    thick = sorted({w.thickness.value for w in floor.walls})
    # every wall must be 100 or 200 mm (the fixture's thicknesses)
    thick_err = max(min(abs(v - 100), abs(v - 200)) for v in thick)
    solids = [v for v in meta["elements"].values() if v["type"] != "floor_boundary"]
    return {
        "dxf_bytes": dxf.stat().st_size,
        "entities": sum(kinds.values()),
        "entity_kinds": dict(kinds),
        "times_s": {k: round(v, 4) for k, v in t.items()},
        "peak_rss_mb": round((peak_rss_bytes() or 0) / 2**20, 1),
        "glb_bytes": len(glb),
        "canonical_json_bytes": len(canonical),
        "report_bytes": len(report),
        "issues": dict(Counter(i.severity for i in project.issues)),
        "issue_codes": dict(Counter(i.code for i in project.issues)),
        "counts": counts,
        "counts_match_expected": counts == expected,
        "max_thickness_error_mm": thick_err,
        "all_solids_watertight": all(v["watertight"] for v in solids),
        "triangles": sum(v["triangles"] for v in meta["elements"].values()),
    }


def environment() -> dict:
    import importlib.metadata as md

    mem = None
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong)
                for n in ("total", "avail", "tpf", "apf", "tv", "av", "aev")
            ]

        ms = MS()
        ms.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        mem = round(ms.total / 2**30, 1)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        cwd=HERE,
    ).stdout.strip()
    return {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "logical_cores": os.cpu_count(),
        "ram_gib": mem,
        "python": platform.python_version(),
        "packages": {
            p: md.version(p) for p in ("ezdxf", "shapely", "trimesh", "pydantic")
        },
        "git_commit": commit,
        "date": time.strftime("%Y-%m-%d"),
    }


def run_child(dxf: Path, tiles: int, timeout: float) -> dict:
    try:
        p = subprocess.run(
            [sys.executable, __file__, "--child", str(dxf), str(tiles)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout:.0f} s"}
    if p.returncode != 0:
        return {"error": (p.stderr or p.stdout).strip()[-400:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def summarise(runs: list[dict]) -> dict:
    ok = [r for r in runs if "error" not in r]
    if not ok:
        return {"error": runs[0]["error"]}
    out = dict(ok[0])  # static facts from the first run
    out["time_stats"] = {}
    for key in ("total", "parse", "interpret", "geometry3d", "glb_export"):
        v = [r["times_s"][key] for r in ok]
        out["time_stats"][key] = {
            "median": round(statistics.median(v), 3),
            "min": round(min(v), 3),
            "max": round(max(v), 3),
        }
    m = [r["peak_rss_mb"] for r in ok]
    out["peak_rss_mb_median"], out["peak_rss_mb_max"] = statistics.median(m), max(m)
    out["runs"] = len(ok)
    out["all_counts_match"] = all(r["counts_match_expected"] for r in ok)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", nargs=2, metavar=("DXF", "TILES"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-seconds", type=float, default=600)
    ap.add_argument("--out", type=Path, default=HERE.parent / "benchmarks")
    ap.add_argument(
        "--diagnostic-no-plugs",
        action="store_true",
        help="DIAGNOSTIC: skip the cubic jamb-pair check; larger sizes, 1 run each",
    )
    a = ap.parse_args()
    if a.child:
        print(json.dumps(child(Path(a.child[0]), int(a.child[1]))))
        return

    from make_fixture_d import make

    if a.diagnostic_no_plugs:
        os.environ["BENCH_NO_PLUGS"] = "1"
        counts = [(k, k) for k in (2, 4, 6, 8, 10, 12, 16, 20)]
        a.repeats, a.max_seconds = 1, 120
    else:
        counts = TILE_COUNTS

    a.out.mkdir(parents=True, exist_ok=True)
    result = {"environment": environment(), "scale": [], "extent": []}
    print(json.dumps(result["environment"], indent=2))
    with tempfile.TemporaryDirectory() as tmp:
        for rows, cols in counts:
            n = rows * cols
            dxf = Path(tmp) / f"d_{rows}x{cols}.dxf"
            make(rows, cols, dxf)
            runs = [run_child(dxf, n, a.max_seconds * 2)]
            first = runs[0].get("times_s", {}).get("total", 0)
            while "error" not in runs[0] and first <= SLOW_S and len(runs) < a.repeats:
                runs.append(run_child(dxf, n, a.max_seconds * 2))
            row = {"tiles": n, "grid": f"{rows}x{cols}", **summarise(runs)}
            result["scale"].append(row)
            print(
                n,
                "tiles:",
                row.get("time_stats", {}).get("total"),
                row.get("error", ""),
                flush=True,
            )
            if "error" in row or row["time_stats"]["total"]["median"] > a.max_seconds:
                print("stopping scale series: failed or over the time budget")
                break
        for off in [] if a.diagnostic_no_plugs else OFFSETS:
            dxf = Path(tmp) / f"e_{int(off)}.dxf"
            make(1, 1, dxf, offset_mm=off)
            row = {"offset_mm": off, **summarise([run_child(dxf, 1, 120)])}
            result["extent"].append(row)
            print(
                "offset",
                off,
                row.get("counts_match_expected"),
                row.get("max_thickness_error_mm"),
                flush=True,
            )
    path = a.out / (
        "t21-diagnostic-no-plugs.json" if a.diagnostic_no_plugs else "t21-results.json"
    )
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
