import math
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from api import building as _building  # noqa: F401  (registers its routes on the projects routers)
from api.auth import router as auth_router
from api.generations import public_router as generations_public
from api.generations import router as generations_router
from api.jobs import recover_jobs
from api.jobs import router as jobs_router
from api.layer_conventions import router as conventions_router
from api.projects import public_router as projects_public
from api.projects import router as projects_router
from api.sharing import router as sharing_router
from api.uploads import router as uploads_router


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    recover_jobs()  # single runner: jobs left running by a dead process can never finish
    yield


def _load_dotenv() -> None:
    """Fill os.environ from the repo-root .env without overriding real env vars.
    Skipped under pytest so a dev's OAuth/DB values never leak into tests."""
    path = Path(__file__).resolve().parents[4] / ".env"
    if "pytest" in sys.modules or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()
app = FastAPI(title="Architectural Reconstruction API", lifespan=_lifespan)
# Browser origins allowed to call the API (local web dev by default).
_ORIGINS = os.environ.get(
    "API_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
# signed cookie that only carries OAuth state/next across the provider redirect
# shortcut: random per-process secret; set SESSION_SECRET when running several workers
app.add_middleware(
    SessionMiddleware,
    session_cookie="oauth_state",  # must differ from the auth cookie ("session") or it overwrites it
    secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
    max_age=600,
    same_site="lax",
    https_only=os.environ.get("AUTH_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
)
app.include_router(auth_router)
app.include_router(uploads_router)
app.include_router(generations_router)
app.include_router(projects_router)
app.include_router(projects_public)
app.include_router(generations_public)
app.include_router(sharing_router)
app.include_router(jobs_router)
app.include_router(conventions_router)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    # NaN/inf cannot be JSON-encoded, so echo such inputs as strings ("nan", "inf")
    errors = [
        {**e, "input": str(e["input"])}
        if isinstance(e.get("input"), float) and not math.isfinite(e["input"])
        else e
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
