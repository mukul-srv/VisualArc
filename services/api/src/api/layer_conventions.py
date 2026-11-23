"""Layer conventions API: the presets, a project's saved mapping and an upload's layer inventory.

Viewers read a project's conventions; owners and editors change them (same rules as floors).
"""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.access import owned
from api.auth import CurrentUser, current_user
from api.db import ProjectConventionsRow, ProjectRow, UploadRow, session
from api.engine.adapters.dxf.reader import (
    USER_UNITS,
    InputError,
    load_doc,
    read_dxf,
    resolve_scale,
)
from api.engine.adapters.dxf.split import detect_floors
from api.engine.conventions import PRESETS, ROLES, known_roles, layer_roles, resolve
from api.generations import ConventionsSpec
from api.storage import upload_path

# preflight issues that mean "the user must supply this parameter"
_NEEDS = {"units_missing": "units"}  # heights are never asked: presets fill them, tagged


router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])


def save_conventions(db: Session, pid: str, spec: ConventionsSpec) -> None:
    """Upsert in the caller's transaction (the caller checked editor access)."""
    row = db.get(ProjectConventionsRow, pid)
    if row is None:
        db.add(ProjectConventionsRow(project_id=pid, preset=spec.preset, mapping=spec.mapping))
    else:
        row.preset, row.mapping = spec.preset, spec.mapping


def preflight(path, project, settings, units: str | None = None, units_override: bool = False) -> dict:
    """What the form needs from a read of the upload: issues, required params, floor candidates."""
    codes = {i.code for i in project.issues}
    candidates = []
    if "floor_split_unconfirmed" in codes:  # read_dxf already checked the units
        doc = load_doc(path)
        candidates = [c.to_dict() for c in detect_floors(doc, resolve_scale(doc, units, units_override), settings).candidates]
    return {
        "issues": [i.model_dump(mode="json") for i in project.issues],
        "needs": sorted(v for k, v in _NEEDS.items() if k in codes),
        "floor_candidates": candidates,
    }


@router.get("/conventions")
def get_presets() -> dict:
    return {
        "roles": list(ROLES),
        "presets": [{"id": p.id, "label": p.label, "source": p.source,
                     "layers": dict(sorted(known_roles(p.settings).items()))}
                    for p in PRESETS.values()],
    }


@router.get("/projects/{pid}/conventions")
def get_project_conventions(pid: str, user: CurrentUser):
    with session() as db:
        owned(db, ProjectRow, pid, user.id, "unknown project", need="viewer")
        row = db.get(ProjectConventionsRow, pid)
        return {"preset": row.preset, "mapping": row.mapping} if row else {"preset": "aia", "mapping": {}}


@router.put("/projects/{pid}/conventions")
def put_project_conventions(pid: str, spec: ConventionsSpec, user: CurrentUser):
    with session() as db, db.begin():
        owned(db, ProjectRow, pid, user.id, "unknown project", lock=True, need="editor")
        save_conventions(db, pid, spec)
    return spec.model_dump()


@router.post("/uploads/{upload_id}/layers")
def upload_layers(upload_id: str, spec: ConventionsSpec, user: CurrentUser,
                  units: str | None = None, units_override: bool = False):
    """Every layer of the upload with its entity count and role under these conventions;
    `role: null` = unmapped (the engine will report it, never drop it silently)."""
    with session() as db:
        owned(db, UploadRow, upload_id, user.id, "unknown upload_id")
    path = upload_path(upload_id)
    if not path.is_file():
        raise HTTPException(404, "unknown upload_id")
    settings = resolve(spec.preset, spec.mapping)
    if units is not None and units not in USER_UNITS:
        raise HTTPException(422, f"unknown units {units!r}")
    try:
        counts = Counter(e.dxf.layer for e in load_doc(path).modelspace())
        project = read_dxf(path, building_type="residential", settings=settings,
                           user_units=units, units_override=units_override)
    except InputError as e:
        raise HTTPException(422, str(e).replace(str(path), "the uploaded file")) from e
    roles = layer_roles(spec.preset, spec.mapping, sorted(counts))
    # the preflight under these conventions, so the form sees the issues the mapping resolves
    return {"layers": [{**r, "entities": counts[r["layer"]]} for r in roles],
            **preflight(path, project, settings, units, units_override)}
