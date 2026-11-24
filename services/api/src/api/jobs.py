"""Background generation jobs: DB job table + one in-process worker thread (no broker).

POST starts a job (access checked up front, the work runs on the single worker); the client polls
GET /jobs/{id} for status/stage/progress and the final result or error. Kinds: generation, floor, parameters (regenerate every floor), draft (review, stores nothing), edits (one floor's user edits). Stages: queued, parsing,
building-model, exporting, done. A blocking-issue outcome is a failed job whose `result` holds the
issues. shortcut: a single runner in one API process; on startup `recover_jobs` fails whatever the
previous process left queued or running. Move to a real queue before running several API workers.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import update

from api.access import owned, project_role
from api.auth import CurrentUser, current_user
from api.db import JobRow, ProjectRow, UploadRow, session
from api.draft import DraftRequest, run_draft
from api.engine.edits import EditsRequest
from api.generations import GenerationRequest, result, run_generation
from api.projects import (
    FloorRequest,
    ParametersRequest,
    _floor,
    add_floor,
    apply_edits,
    check_regenerable,
    parameter_overrides,
    regenerate,
)
from api.storage import new_id

router = APIRouter(prefix="/api/v1/jobs", dependencies=[Depends(current_user)])
log = logging.getLogger(__name__)

STAGES = {"queued": 0, "parsing": 10, "building-model": 50, "exporting": 75, "done": 100}
RESTART_ERROR = "The API restarted while this job was running; start it again."

# created at import: the single-runner invariant must not depend on a lazy-init race
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")


def submit(job_id: str) -> None:
    _pool.submit(execute, job_id)


def _set(job_id: str, **fields) -> None:
    with session() as db, db.begin():
        db.execute(update(JobRow).where(JobRow.id == job_id).values(
            updated_at=datetime.now(UTC), **fields))


def _fail(job_id: str, error: str, result: dict | None = None) -> None:
    """Best effort: a DB error here is logged; recover_jobs cleans up on the next start."""
    try:
        _set(job_id, status="failed", error=error[:2000], result=result)
    except Exception:
        log.exception("job %s: could not record failure", job_id)


def _detail(e: HTTPException) -> str:
    return e.detail if isinstance(e.detail, str) else json.dumps(e.detail)


def execute(job_id: str) -> None:
    """Run one job to a terminal state; never raises. Engine input errors (HTTPException, written
    for the user) are stored as is; anything else is stored generically and logged in full."""
    stage = "queued"

    def progress(new: str) -> None:
        nonlocal stage
        _set(job_id, stage=new, progress=STAGES[new])
        stage = new

    try:
        with session() as db:
            job = db.get(JobRow, job_id)
            if job is None or job.status != "queued":
                return
            kind, owner, pid, request = job.kind, job.owner_id, job.project_id, job.request
        _set(job_id, status="running")
        if kind == "floor":
            out = add_floor(pid, FloorRequest(**request), None, owner, progress=progress)
        elif kind == "draft":  # stores nothing; blocking issues are part of the result
            out = run_draft(DraftRequest(**request), owner, progress=progress)
        elif kind == "edits":
            out = apply_edits(pid, request["floor_id"], request["edits"], owner, progress=progress)
        elif kind == "parameters":
            out = regenerate(pid, request, owner, progress=progress)
        else:
            gid, issues = run_generation(GenerationRequest(**request), owner, progress=progress)
            out = (JSONResponse(status_code=409, content={"issues": issues}) if gid is None
                   else result(gid, issues))
        if isinstance(out, JSONResponse):  # blocking issues: nothing stored
            _fail(job_id, "Blocking issues; no model generated.",
                  {"issues": json.loads(out.body)["issues"]})
        else:
            _set(job_id, status="succeeded", stage="done", progress=100, result=out)
    except HTTPException as e:
        _fail(job_id, _detail(e))
    except Exception:
        log.exception("job %s failed during %s", job_id, stage)
        _fail(job_id, f"Generation failed during {stage}. Try again; if it keeps failing, contact the operator.")


def recover_jobs() -> int:
    """Fail jobs a previous process left queued or running. Returns how many."""
    with session() as db, db.begin():
        r = db.execute(update(JobRow).where(JobRow.status.in_(("queued", "running"))).values(
            status="failed", error=RESTART_ERROR, updated_at=datetime.now(UTC)))
        return r.rowcount


def _create(db, user, kind: str, pid: str | None, request: dict) -> JobRow:
    job = JobRow(id=new_id(), owner_id=user.id, project_id=pid, kind=kind, status="queued",
                 stage="queued", progress=0, request=request)
    db.add(job)
    return job


def _start(user, kind: str, pid: str | None, req) -> JSONResponse:
    with session() as db, db.begin():
        owned(db, UploadRow, req.upload_id, user.id, "unknown upload_id")
        if pid is not None:
            owned(db, ProjectRow, pid, user.id, "unknown project", need="editor")
        # exclude_unset: which fields the caller set matters (project parameters fill the rest)
        job = _create(db, user, kind, pid, req.model_dump(mode="json", exclude_unset=True))
        jid = job.id
    submit(jid)
    return JSONResponse(status_code=202, content={"job_id": jid})


@router.post("/generations", status_code=202)
def start_generation(req: GenerationRequest, user: CurrentUser):
    return _start(user, "generation", None, req)


@router.post("/uploads/{upload_id}/draft", status_code=202)
def start_draft(upload_id: str, req: DraftRequest, user: CurrentUser):
    """Guided review before saving: per floor issues, stats and plan overlay; nothing is stored."""
    req.upload_id = upload_id
    return _start(user, "draft", None, req)


@router.post("/projects/{pid}/floors", status_code=202)
def start_floor(pid: str, req: FloorRequest, user: CurrentUser):
    return _start(user, "floor", pid, req)


@router.post("/projects/{pid}/parameters", status_code=202)
def start_parameters(pid: str, req: ParametersRequest, user: CurrentUser):
    """Set (value) or reset (null) project parameters and regenerate every floor, as a job."""
    overrides = parameter_overrides(req)
    if not overrides:
        raise HTTPException(422, "no parameters given")
    with session() as db, db.begin():
        check_regenerable(db, pid, user.id)
        jid = _create(db, user, "parameters", pid, overrides).id
    submit(jid)
    return JSONResponse(status_code=202, content={"job_id": jid})


@router.put("/projects/{pid}/floors/{floor_id}/edits", status_code=202)
def start_edits(pid: str, floor_id: str, req: EditsRequest, user: CurrentUser):
    """Replace the floor's edits (the full ordered list) and regenerate that floor, as a job."""
    with session() as db, db.begin():
        check_regenerable(db, pid, user.id)
        _floor(owned(db, ProjectRow, pid, user.id, "unknown project", need="editor"), floor_id)
        jid = _create(db, user, "edits", pid, {"floor_id": floor_id, "edits": req.model_dump(mode="json")["edits"]}).id
    submit(jid)
    return JSONResponse(status_code=202, content={"job_id": jid})


@router.get("/{job_id}")
def get_job(job_id: str, user: CurrentUser):
    """Starter, or anyone with viewer access to the job's project."""
    with session() as db:
        job = db.get(JobRow, job_id) if len(job_id) == 32 else None
        ok = job is not None and (job.owner_id == user.id or (
            job.project_id is not None
            and (p := db.get(ProjectRow, job.project_id)) is not None
            and project_role(db, p, user.id) is not None))
        if not ok:
            raise HTTPException(404, "unknown job")
        return {"id": job.id, "kind": job.kind, "project_id": job.project_id, "status": job.status,
                "stage": job.stage, "progress": job.progress, "error": job.error,
                "result": job.result, "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat()}
