from fastapi import FastAPI

app = FastAPI(title="Architectural Reconstruction API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
