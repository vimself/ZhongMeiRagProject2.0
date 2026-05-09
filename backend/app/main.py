from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.auth import api_limiter
from app.api.auth import router as auth_router
from app.api.health import router as health_router
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
    app.include_router(health_router)
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    return app


app = create_app()
