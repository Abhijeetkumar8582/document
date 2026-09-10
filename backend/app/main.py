import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models, worker  # noqa: F401  (models registers tables)
from .database import migrate
from .routers import audit_log, batches, dashboard, records, uploads

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

migrate()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker.pool.start()
    yield
    worker.pool.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Registrar API",
    description="Upload academic records, extract their contents, and keep a structured, audited register.",
    version="3.0.0",
)

# Browser origins allowed to call this API. Comma-separated in CORS_ORIGINS; add the deployed frontend's origin there.
_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://15.207.14.33,http://15.207.14.33:8000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(records.router)
app.include_router(audit_log.router)
app.include_router(batches.router)
app.include_router(uploads.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --- Serve the built frontend from the same process -----------------------------------
# `npm run build` in frontend/ writes frontend/dist. When it exists, this API also serves the app at "/",
# so one uvicorn on one port is the whole deployment and the browser never crosses origins.
_dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"))
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = _dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")

    logging.getLogger("registrar").info("serving frontend from %s", _dist)
else:
    logging.getLogger("registrar").info("no frontend build at %s; API only (run `npm run build` in frontend/)", _dist)
