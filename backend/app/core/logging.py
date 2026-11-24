"""Structured JSON logging and request-id context (design B01 §3.3).

- `configure_logging()` routes structlog AND stdlib loggers (uvicorn,
  sqlalchemy, arq) through one JSON renderer on stdout (system_design §10).
- `RequestContextMiddleware` gives every HTTP request a request id, binds it
  (plus method/path/client ip) into contextvars so every log line and audit
  line of that request carries it, and writes one access log line.
"""

import logging
import re
import sys
import time
import uuid
from typing import Any, TextIO

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
# D3: only short, safe ids are accepted from clients. Anything else (newlines,
# quotes, very long values) could forge or corrupt log/audit lines, so it is
# replaced by a server-generated UUID.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# D10: liveness/readiness probes are polled every few seconds by Docker; their
# access lines go to DEBUG so INFO logs stay readable.
QUIET_PATH_PREFIXES = ("/health/",)

access_log = structlog.get_logger("app.access")


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Install JSON logging for structlog and the stdlib root logger.

    Safe to call more than once (tests, worker + app in one process): handlers
    on the root logger are replaced, not stacked. `stream` defaults to stdout;
    the CLI passes stderr so its human-readable output stays on stdout.
    """
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,  # request_id etc.
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared,
            # Hand off to the stdlib formatter below, so both worlds render alike.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,  # applied to plain logging.* records
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,  # traceback -> "exception" field
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers; strip them so its lines are JSON too.
    # uvicorn.access is silenced because the middleware writes a richer line.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _resolve_request_id(raw: str | None) -> str:
    """Return the client's id if it is safe, else a fresh UUID4 (D3)."""
    if raw and REQUEST_ID_PATTERN.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


def get_request_id() -> str | None:
    """Request id of the current request, or None outside a request."""
    return structlog.contextvars.get_contextvars().get("request_id")


def get_client_ip() -> str | None:
    """Socket peer of the current request (proxy headers are trusted only from B13)."""
    return structlog.contextvars.get_contextvars().get("client_ip")


class RequestContextMiddleware:
    """Pure ASGI middleware (cheaper than BaseHTTPMiddleware, streaming-safe)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = _resolve_request_id(headers.get(REQUEST_ID_HEADER.lower()))
        client = scope.get("client")
        path: str = scope.get("path", "")

        # contextvars are per-task, so concurrent requests never see each other's ids.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope.get("method"),
            path=path,
            client_ip=client[0] if client else None,
        )
        # Also expose it on request.state for handlers that want it directly.
        scope.setdefault("state", {})["request_id"] = request_id

        status_holder = {"status": 500}  # stays 500 if the app crashes before responding
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw = list(message.get("headers", []))
                raw.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            quiet = path.startswith(QUIET_PATH_PREFIXES) and status_holder["status"] < 500
            log = access_log.debug if quiet else access_log.info
            log("request.done", status=status_holder["status"], duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()
