import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
