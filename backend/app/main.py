from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.admin import router as admin_router
from app.api.auth import api_limiter
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.knowledge_base import admin_router as kb_admin_router
from app.api.knowledge_base import router as kb_router
from app.api.user import router as user_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.middleware.trace_id import TraceIdMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.limiter = api_limiter
    app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(TraceIdMiddleware)
    app.include_router(auth_router)
    app.include_router(user_router)
    app.include_router(admin_router)
    app.include_router(kb_router)
    app.include_router(kb_admin_router)
    app.include_router(documents_router)
    app.include_router(health_router)

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    return app


app = create_app()
