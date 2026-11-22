"""Background generation jobs: DB job table + one in-process worker thread (no broker).

POST starts a job (access checked up front, the work runs on the single worker); the client polls
GET /jobs/{id} for status/stage/progress and the final result or error. Stages: queued, parsing,
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
from api.generations import GenerationRequest, result, run_generation
from api.projects import FloorRequest, add_floor
from api.storage import new_id

router = APIRouter(prefix="/api/v1/jobs", dependencies=[Depends(current_user)])
log = logging.getLogger(__name__)

STAGES = {"queued": 0, "parsing": 10, "building-model": 50, "exporting": 75, "done": 100}
RESTART_ERROR = "The API restarted while this job was running; start it again."

_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")
    return _pool


def submit(job_id: str) -> None:
    _executor().submit(execute, job_id)


def _set(job_id: str, **fields) -> None:
    with session() as db, db.begin():
        db.execute(update(JobRow).where(JobRow.id == job_id).values(
            updated_at=datetime.now(UTC), **fields))


def _stage(job_id: str):
    def progress(stage: str) -> None:
        _set(job_id, stage=stage, progress=STAGES[stage])
    return progress


def _detail(e: HTTPException) -> str:
    return e.detail if isinstance(e.detail, str) else json.dumps(e.detail)


def execute(job_id: str) -> None:
    """Run one job to a terminal state; never raises."""
    with session() as db:
        job = db.get(JobRow, job_id)
        if job is None or job.status != "queued":
            return
        kind, owner, pid, request = job.kind, job.owner_id, job.project_id, job.request
    _set(job_id, status="running")
    progress = _stage(job_id)
    try:
        if kind == "floor":
            out = add_floor(pid, FloorRequest(**request), None, owner, progress=progress)
        else:
            gid, issues = run_generation(GenerationRequest(**request), owner, progress=progress)
            out = JSONResponse(status_code=409, content={"issues": issues}) if gid is None                 else result(gid, issues)
        if isinstance(out, JSONResponse):  # blocking issues: nothing stored
            issues = json.loads(out.body)["issues"]
            return _set(job_id, status="failed", error="Blocking issues; no model generated.",
                        result={"issues": issues})
        _set(job_id, status="succeeded", stage="done", progress=100, result=out)
    except HTTPException as e:
        _set(job_id, status="failed", error=_detail(e)[:2000])
    except Exception as e:
        log.exception("job %s failed", job_id)
        _set(job_id, status="failed", error=f"Unexpected error: {type(e).__name__}: {e}"[:2000])


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
        job = _create(db, user, kind, pid, req.model_dump(mode="json"))
        jid = job.id
    submit(jid)
    return JSONResponse(status_code=202, content={"job_id": jid})


@router.post("/generations", status_code=202)
def start_generation(req: GenerationRequest, user: CurrentUser):
    return _start(user, "generation", None, req)


@router.post("/projects/{pid}/floors", status_code=202)
def start_floor(pid: str, req: FloorRequest, user: CurrentUser):
    return _start(user, "floor", pid, req)


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
