"""Application factory and module registry (design B01 §3.7).

Adding a business module = add its name to app/modules/registry.py MODULES
(deliverables.md reusability rule 1, design B06 D3). Nothing in this file
changes for a new module.

Middleware order, outermost first:
  RequestContextMiddleware  request id + access log (must see every response)
  CORSMiddleware            so even 500 responses carry CORS headers
  CatchAllMiddleware        unhandled exception -> 500 standard body, inside
                            the request context (see core/errors.py)
  FastAPI routing + exception handlers for expected errors
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.config import APP_VERSION, Settings, get_settings
from app.core import audit, db
from app.core.errors import CatchAllMiddleware, register_error_handlers
from app.core.logging import REQUEST_ID_HEADER, RequestContextMiddleware, configure_logging
from app.modules import registry

log = structlog.get_logger("app.main")

# D4: startup waits up to DB_CONNECT_ATTEMPTS * DB_CONNECT_DELAY_S for Postgres,
# then exits non-zero so Docker restarts / reports the container.
DB_CONNECT_ATTEMPTS = 5
DB_CONNECT_DELAY_S = 2.0


def _operation_id(route: APIRoute) -> str:
    """OpenAPI operationId for a route: its endpoint function name (B08 D14)."""
    return route.name


async def _connect_db_with_retry(url: str) -> None:
    db.init_engine(url)
    for attempt in range(1, DB_CONNECT_ATTEMPTS + 1):
        try:
            await db.ping()
            log.info("db.connected", attempt=attempt)
            return
        except Exception as exc:
            log.warning(
                "db.connect_failed",
                attempt=attempt,
                of=DB_CONNECT_ATTEMPTS,
                error=f"{type(exc).__name__}: {exc}",
            )
            if attempt == DB_CONNECT_ATTEMPTS:
                raise RuntimeError("database unreachable at startup") from exc
            await asyncio.sleep(DB_CONNECT_DELAY_S)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Pass `settings` in tests; production uses env."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail fast on an unwritable audit dir BEFORE accepting traffic (D4):
        # running without an audit trail is not an acceptable degraded mode.
        audit.init_audit(settings.audit_log_dir, fail_closed=settings.audit_fail_closed)
        try:
            await _connect_db_with_retry(settings.database_url)
        except Exception:
            # Startup aborted: release what was opened so nothing (pooled
            # connections, a half-initialised engine) outlives the failed app.
            await db.dispose_engine()
            audit.close_audit()
            raise
        # Redis client is lazy: it connects on first command, so a Redis outage
        # degrades readiness instead of blocking startup. ArqRedis is a Redis
        # subclass that can also enqueue jobs (B03 D13: one client for health,
        # rate limits and the email queue).
        app.state.redis = ArqRedis.from_url(
            settings.redis_url, socket_timeout=2, socket_connect_timeout=2
        )
        log.info(
            "app.started",
            env=settings.app_env,
            version=APP_VERSION,
            modules=registry.MODULES,
        )
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await db.dispose_engine()
            audit.close_audit()
            log.info("app.stopped")

    app = FastAPI(
        title="Core SaaS API",
        version=APP_VERSION,
        lifespan=lifespan,
        # API docs are a dev aid; hidden in prod (api_spec.md header).
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
        # B08 D14: operationId = the route function name ("me", "login", ...)
        # so the orval-generated hooks read useMe/useLogin instead of
        # useMeMeGet. Route function names must therefore be unique across
        # modules; tests/test_openapi_ids.py guards that.
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings

    register_error_handlers(app)

    # add_middleware() wraps: the LAST one added is the OUTERMOST.
    app.add_middleware(CatchAllMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # cookies (auth arrives in B03)
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestContextMiddleware)

    # Routers carry their own prefix (/files, /health, ...).
    for name, router in registry.load_routers():
        app.include_router(router)
        log.debug("app.module_loaded", module=name)

    return app


def __getattr__(name: str) -> FastAPI:
    """`uvicorn app.main:app` entry point, built on first access.

    Lazy so that importing this module (tests, tooling) does not read the
    environment or configure logging as a side effect.
    """
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
