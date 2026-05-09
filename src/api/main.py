"""Application FastAPI Artiste Coloriage."""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from artiste_logging import setup_logging

setup_logging("api")

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import ai, benchmark, generation, images, jobs, review, sites, taxonomy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

logger = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Synchronise ``job_type_config`` (types manquants après migration / DB vide)."""
    from api.db import SessionLocal, ensure_default_job_types

    session = SessionLocal()
    try:
        ensure_default_job_types(session)
        session.commit()
    except Exception as e:
        logger.warning("Synchronisation job_type_config au démarrage ignorée : %s", e)
        session.rollback()
    finally:
        session.close()
    yield


app = FastAPI(
    title="Artiste Coloriage API",
    description="API pour la taxonomie, images, collections et exports",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log toutes les requêtes + réponses, y compris les 500."""
    logger.info("→ %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning("← %s %s → HTTP %s", request.method, request.url.path, response.status_code)
        else:
            logger.info("← %s %s → HTTP %s", request.method, request.url.path, response.status_code)
        return response
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("UNHANDLED EXCEPTION %s %s\n%s", request.method, request.url.path, tb)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Erreur interne non gérée : {type(exc).__name__}: {exc}"},
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all : log le traceback complet et renvoie le message dans le detail."""
    tb = traceback.format_exc()
    logger.error("EXCEPTION HANDLER %s %s\n%s", request.method, request.url.path, tb)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


app.include_router(taxonomy.router)
app.include_router(ai.router)
app.include_router(generation.router)
app.include_router(images.router)
app.include_router(jobs.router)
app.include_router(sites.router)
app.include_router(benchmark.router)
app.include_router(review.router)

if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR), html=True), name="data")


@app.get("/")
def root():
    return {
        "message": "Artiste Coloriage API",
        "docs": "/docs",
        "taxonomy": "/api/taxonomy",
        "editor": "/data/taxonomy_editor.html",
        "admin": "/data/admin.html",
        "jobs_editor": "/data/jobs_editor.html",
        "ai_status": "/api/ai/status",
        "images": "/api/images",
        "jobs": "/api/jobs",
        "sites": "/api/sites",
        "generation_presets": "/api/generation/presets",
    }
