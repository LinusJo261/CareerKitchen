from __future__ import annotations

import logging
import re
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from starlette.exceptions import HTTPException

from app.core.errors import AppError
from app.core.settings import get_settings
from app.schemas import responses as r
from app.schemas.core import ErrorEnvelope


def create_app(settings=None, engine=None) -> FastAPI:
    from app.api.core import router
    from app.api.navigation import router as navigation_router
    from app.api.pact import router as pact_router
    from app.api.research import router as research_router

    settings = settings or get_settings()
    app = FastAPI(
        title="Career Kitchen API",
        version="0.1.0",
        description="Persistent reciprocal hiring API. Readiness, mutual interest, accepted offers and verified starts are separate. Experimental plans are read-only and cannot certify reliability.",
    )
    app.state.settings = settings
    app.state.engine = engine or create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000 -c lock_timeout=10000"},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Idempotency-Replayed"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    def error(request, status, code, message, fields=None):
        body = {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
        }
        if fields:
            body["fields"] = fields
        return JSONResponse({"error": body}, status_code=status)

    @app.middleware("http")
    async def secure_headers(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied if re.fullmatch(r"[A-Za-z0-9-]{1,100}", supplied) else str(uuid4())
        )
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin not in settings.cors_origins
        ):
            response = error(request, 403, "ORIGIN_FORBIDDEN", "Origin is not allowed")
        elif not request.headers.get("content-length", "0").isdigit():
            response = error(request, 422, "INVALID_CONTENT_LENGTH", "Invalid Content-Length")
        elif int(request.headers.get("content-length", "0") or 0) > settings.max_resume_bytes + 100000:
            response = error(request, 413, "REQUEST_TOO_LARGE", "Request exceeds the size limit")
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": request.state.request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"
                if request.url.path not in {"/docs", "/redoc"}
                else "frame-ancestors 'none'",
            }
        )
        return response

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(
            request,
            exc.status_code,
            "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
            "Resource was not found" if exc.status_code == 404 else "Request is not permitted",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo input values (which may contain private data or tokens).
        return error(
            request,
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
            [{"field": ".".join(str(x) for x in item["loc"]), "type": item["type"]} for item in exc.errors()],
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        logging.getLogger("career_kitchen").error(
            "request_failed request_id=%s exception_type=%s", request.state.request_id, type(exc).__name__
        )
        return error(request, 500, "INTERNAL_ERROR", "The request could not be completed")

    @app.get("/v1/health", tags=["operations"], response_model=r.Envelope[r.HealthOut])
    def health():
        return {"data": {"status": "alive"}}

    @app.get(
        "/v1/ready",
        tags=["operations"],
        response_model=r.Envelope[r.ReadyOut],
        responses={401: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}},
    )
    def ready(request: Request):
        import hmac

        if settings.environment in {"production", "staging"} and not hmac.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + settings.readiness_token.get_secret_value()
        ):
            raise AppError(401, "UNAUTHORIZED", "Readiness credential required")
        try:
            with app.state.engine.connect() as conn:
                revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
                if revision != "0005_congestion_prices":
                    raise ValueError("Schema mismatch")
            return {"data": {"status": "ready", "queue": "POSTGRES_OUTBOX"}}
        except Exception as exc:
            raise AppError(503, "NOT_READY", "Database schema or persistent queue is unavailable") from exc

    app.include_router(router, prefix="/v1")
    app.include_router(pact_router, prefix="/v1")
    app.include_router(research_router, prefix="/v1")
    app.include_router(navigation_router, prefix="/v1")
    # OpenAPI represents every authenticated route and write idempotency requirement.
    original_openapi = app.openapi

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["SupabaseBearer"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        for path, operations in schema["paths"].items():
            if path in {"/v1/health", "/v1/ready"}:
                continue
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if path.endswith("/shortlist/approve"):
                    operation["responses"].pop("200", None)
                for status in (401, 403, 404, 409, 412, 413, 415, 422, 429, 500, 503):
                    operation["responses"][str(status)] = {
                        "description": HTTPStatus(status).phrase,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
                        },
                    }
                operation["security"] = [{"SupabaseBearer": []}]
                if method != "get":
                    operation.setdefault("parameters", []).append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "minLength": 8, "maxLength": 128},
                            "description": "Persisted for seven days; same actor/route/key with a different request returns 409",
                        }
                    )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


app = create_app()
