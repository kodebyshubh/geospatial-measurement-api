"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import files, health
from app.config import get_settings
from app.db import get_engine, init_db
from app.errors import register_exception_handlers
from app.logging_config import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    init_db(get_engine())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Geospatial File Measurement API",
        description="Upload a zipped Shapefile or a KML and get areas and lengths in meters.",
        version="1.0.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(files.router)
    return app


app = create_app()
