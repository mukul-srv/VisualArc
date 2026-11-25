"""OBJ / IFC downloads (Phase 1/21), built on demand from the stored canonical models.

A project exports all its floors (stacked by their own elevation, each shifted by its plan offset like
the viewer does); a standalone generation exports its one floor. Same access as the GLB artifact:
viewer role or the share link. Blocked generations have no canonical model stored, so they give 404.
"""

import json
import re
from typing import Literal

from fastapi import HTTPException, Response

from api.access import owned
from api.db import GenerationRow, ProjectRow, session
from api.engine.canonical.model import Project
from api.engine.exporters.ifc import build_ifc
from api.engine.exporters.obj import build_obj
from api.generations import public_router as generations_public
from api.projects import _latest
from api.projects import public_router as projects_public
from api.sharing import Principal
from api.storage import blob_path

Format = Literal["obj", "ifc"]
MEDIA = {"obj": "model/obj", "ifc": "application/x-step"}


def _canonical(prefix: str) -> Project:
    try:
        return Project.model_validate(json.loads(blob_path(f"{prefix}/model.canonical.json").read_text("utf-8")))
    except (OSError, ValueError) as e:
        raise HTTPException(404, "not found") from e


def _export(fmt: Format, floors: list[tuple[Project, tuple[float, float]]], name: str) -> Response:
    if not any(b.floors for p, _ in floors for b in p.buildings):
        raise HTTPException(404, "nothing to export")
    body = build_obj(floors)[0].encode() if fmt == "obj" else build_ifc(floors)[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "model"
    return Response(body, media_type=MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'})


@projects_public.get("/projects/{pid}/export/{fmt}")
def export_project(pid: str, fmt: Format, who: Principal):
    with session() as db:
        row = owned(db, ProjectRow, pid, who, "unknown project", need="viewer")
        mfs = sorted(_latest(db, pid).snapshot["floors"], key=lambda f: f["elevation"]["value"])
        floors = []
        for mf in mfs:
            g = db.get(GenerationRow, mf["generation_id"])
            o = mf.get("offset") or {}
            if g is not None:
                floors.append((_canonical(g.blob_prefix), (o.get("x", 0.0), o.get("y", 0.0))))
        name = row.data["name"]
    return _export(fmt, floors, name)


@generations_public.get("/generations/{generation_id}/export/{fmt}")
def export_generation(generation_id: str, fmt: Format, who: Principal):
    with session() as db:
        g = owned(db, GenerationRow, generation_id, who, "not found", need="viewer")
        project, name = _canonical(g.blob_prefix), g.name or generation_id
    return _export(fmt, [(project, (0.0, 0.0))], name)
