import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.generations import router as generations_router
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
