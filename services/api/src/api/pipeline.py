"""Shared build step for the CLI and the API: project -> files on disk."""

import json
from pathlib import Path

from api.engine.canonical.model import Project
from api.engine.exporters.glb import build_meta, build_scene
from api.engine.exporters.report import build_report


def has_blocking(project: Project) -> bool:
    return any(i.severity == "blocking" for i in project.issues)


def write_artifacts(
    project: Project, out: Path, stem: str, expected: Project | None = None, progress=None
) -> list[str]:
    """Write canonical JSON + report always (they explain a block); GLB + meta
    only when nothing blocks. Returns the names of the files written."""
    out.mkdir(parents=True, exist_ok=True)
    names = [f"{stem}.canonical.json", f"{stem}.report.md"]
    (out / names[0]).write_text(project.model_dump_json(indent=2) + "\n", "utf-8")
    (out / names[1]).write_text(build_report(project, expected), "utf-8")
    if not has_blocking(project):
        if progress:
            progress("exporting")
        scene = build_scene(project)
        (out / f"{stem}.glb").write_bytes(scene.export(file_type="glb"))
        meta = json.dumps(build_meta(project, scene), indent=2) + "\n"
        (out / f"{stem}.meta.json").write_text(meta, "utf-8")
        names += [f"{stem}.glb", f"{stem}.meta.json"]
    return names
