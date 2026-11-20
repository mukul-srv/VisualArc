from fastapi import FastAPI

from api.uploads import router as uploads_router

app = FastAPI(title="Architectural Reconstruction API")
app.include_router(uploads_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
