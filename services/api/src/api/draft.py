"""Guided review: read the upload (single floor or confirmed split rows) and report per floor
{issues, stats, overlay}. Stores nothing (no GenerationRow, no artifacts); accepting runs the normal
generate/split/add-floor calls, so there is one commit path."""

from api.engine.adapters.dxf.reader import InputError, load_doc, resolve_scale
from api.generations import GenerationRequest, read_project, request_settings
from api.plan_overlay import _segments, overlay_of
from api.storage import upload_path
from api.uploads import FloorConfirm, split_plan


class DraftRequest(GenerationRequest):
    upload_id: str = ""  # the path names the upload
    floors: list[FloorConfirm] | None = None  # split rows of a consolidated DXF; None = one floor


def _entry(project, req, name: str | None, key: str | None, scope) -> dict:
    issues = [i.model_dump(mode="json") for i in project.issues]
    floors = [f for b in project.buildings for f in b.floors]
    out = {"key": key, "name": name, "issues": issues, "stats": None, "overlay": None}
    if not floors:
        return out
    fl = floors[0].model_dump(mode="json")
    out["stats"] = {"walls": len(fl["walls"]), "openings": len(fl["openings"]),
                    "rooms": len(fl["rooms"]),
                    "area": sum(r["area"]["value"] for r in fl["rooms"])}  # mm2
    try:
        doc = load_doc(upload_path(req.upload_id))
        k = resolve_scale(doc, req.units, req.units_override)
    except InputError:
        k = None
    if k is not None:
        segs = _segments(doc, None if scope is None else set(scope.handles), k,
                         (0.0, 0.0) if scope is None else tuple(scope.offset),
                         request_settings(req))
        out["overlay"] = {"unit": "mm", **overlay_of(fl, segs, request_settings(req))}
    return out


def run_draft(req: DraftRequest, owner_id: str, progress=None) -> dict:
    if progress:
        progress("parsing")
    if req.floors is None:
        project = read_project(req, owner_id)
        res = [_entry(project, req, None, None, None)]
    else:
        jobs, _notes, _elev = split_plan(req.upload_id, req, req.floors, owner_id)
        res = []
        for n, (key, freq, scope, why) in enumerate(jobs):
            p = read_project(freq, owner_id, floor_id=f"floor-{n}", floor_name=freq.floor_name.strip(),
                             floor_elevation=freq.elevation, elevation_assumed=why, scope=scope)
            res.append(_entry(p, freq, freq.floor_name, key, scope))
    if progress:
        progress("building-model")
    return {"floors": res,
            "blocking": any(i["severity"] == "blocking" for f in res for i in f["issues"])}
