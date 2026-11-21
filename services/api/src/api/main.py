import math
import os

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.generations import router as generations_router
from api.projects import router as projects_router
from api.uploads import router as uploads_router

app = FastAPI(title="Architectural Reconstruction API")
# Browser origins allowed to call the API (local web dev by default).
_ORIGINS = os.environ.get(
    "API_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(uploads_router)
app.include_router(generations_router)
app.include_router(projects_router)


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
