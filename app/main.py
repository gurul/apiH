"""FastAPI app factory. `uvicorn app.main:app` entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.routers import health, runs, workflows

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    # Import registers the hn_firebase_v0 mapper.
    from app.services import http_executors  # noqa: F401

    yield


def create_app() -> FastAPI:
    application = FastAPI(title="API H", lifespan=lifespan)
    application.include_router(health.router)
    application.include_router(workflows.router)
    application.include_router(runs.router)
    application.mount(
        "/static", StaticFiles(directory=str(STATIC_DIR)), name="static"
    )

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return application


app = create_app()
