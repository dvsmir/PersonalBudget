"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.config import get_settings
from app.services.common import DomainError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def problem(status: int, code: str, title: str, **extra: object) -> JSONResponse:
    """RFC 7807 problem details."""
    return JSONResponse(
        status_code=status,
        content={"type": f"about:blank#{code}", "title": title, "status": status, "code": code, **extra},
        media_type="application/problem+json",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    scheduler = None
    if get_settings().scheduler_enabled:
        from app import jobs

        scheduler = jobs.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Budget API", version="1.0.0", lifespan=lifespan,
                  openapi_url="/api/v1/openapi.json", docs_url="/api/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.message, **exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(422, "validation", "Invalid request", errors=exc.errors())

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
