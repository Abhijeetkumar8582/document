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
from .services import storage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")

migrate()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.sync_bucket_cors(_origins)
    worker.pool.start()
    yield
    worker.pool.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Registrar API",
    description="Upload academic records, extract their contents, and keep a structured, audited register.",
    version="3.0.0",
)

# Browser origins allowed to call this API.
# Default: any origin. There is no login or cookie session yet, so an origin allow-list adds no protection and
# only breaks the app whenever the frontend is served from a new address. Once authentication is added, set
# CORS_ORIGINS to the exact frontend origin(s), comma-separated, and this becomes a real allow-list.
_cors_env = os.getenv("CORS_ORIGINS", "").strip()
_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)
logging.getLogger("registrar").info("CORS: %s", "any origin" if _origins == ["*"] else ", ".join(_origins))

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

    _root = _dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        # Only files inside dist/ are ever served; "../backend/.env" style paths fall back to the app shell.
        candidate = (_root / path).resolve()
        if path and candidate.is_relative_to(_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_root / "index.html")

    logging.getLogger("registrar").info("serving frontend from %s", _dist)
else:
    logging.getLogger("registrar").info("no frontend build at %s; API only (run `npm run build` in frontend/)", _dist)
