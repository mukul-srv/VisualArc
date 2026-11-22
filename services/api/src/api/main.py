import math
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from api.auth import router as auth_router
from api.generations import public_router as generations_public
from api.generations import router as generations_router
from api.projects import public_router as projects_public
from api.projects import router as projects_router
from api.sharing import router as sharing_router
from api.uploads import router as uploads_router

app = FastAPI(title="Architectural Reconstruction API")
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
