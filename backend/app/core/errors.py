"""Error types and handlers: one error body everywhere (design B01 §3.2).

Body (api_spec.md):
    {"error": {"code": "...", "message": "...", "request_id": "...", "fields": [...]?}}

Services raise `AppError` subclasses; they never build HTTP responses.

Note on unhandled exceptions: Starlette runs an `Exception` handler in its
outermost ServerErrorMiddleware, i.e. OUTSIDE our RequestContextMiddleware,
where the request id is gone and the X-Request-ID header cannot be added.
`CatchAllMiddleware` therefore converts unexpected exceptions into the 500
body *inside* the request context instead.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_request_id

log = structlog.get_logger("app.errors")

# HTTP status -> error code for errors raised by the framework itself
# (unknown route, wrong method, ...).
STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class AppError(Exception):
    """Base for every expected error. Subclasses fix status and code."""

    status: int = 500
    code: str = "internal_error"
    default_message: str = "Unexpected error"

    def __init__(
        self,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        fields: list[dict[str, Any]] | None = None,
    ):
        self.message = message or self.default_message
        self.headers = headers
        # Optional per-field details, rendered as error.fields (B03: weak password).
        self.fields = fields
        super().__init__(self.message)


class BadRequest(AppError):
    status, code, default_message = 400, "bad_request", "Malformed request"


class Unauthenticated(AppError):
    status, code, default_message = 401, "unauthenticated", "Authentication required"


class PermissionDenied(AppError):
    status, code, default_message = 403, "permission_denied", "Permission denied"


class NotFound(AppError):
    status, code, default_message = 404, "not_found", "Not found"


class EmailNotVerified(PermissionDenied):
    """B03 D1: logged in, but tenant features need a verified email."""

    code, default_message = "email_not_verified", "Email address not verified"


class Conflict(AppError):
    status, code, default_message = 409, "conflict", "Conflict"


class ValidationFailed(AppError):
    """422 raised by services (not Pydantic), e.g. a password that is too weak."""

    status, code, default_message = 422, "validation_error", "Request validation failed"


class RateLimited(AppError):
    status, code, default_message = 429, "rate_limited", "Too many requests"


class ServiceUnavailable(AppError):
    status, code, default_message = 503, "service_unavailable", "Service unavailable"


def error_body(
    code: str, message: str, fields: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build the standard body; request_id comes from the logging context."""
    err: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if fields is not None:
        err["fields"] = fields
    return {"error": err}


def _log_error(status: int, code: str, message: str) -> None:
    # 4xx are client mistakes (INFO); 5xx are ours (ERROR).
    (log.error if status >= 500 else log.info)(
        "request.error", status=status, code=code, message=message
    )


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered for AppError only
        raise exc
    _log_error(exc.status, exc.code, exc.message)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.fields),
        status_code=exc.status,
        headers=exc.headers,
    )


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered for RequestValidationError only
        raise exc
    # Keep only loc/msg/type: Pydantic's "input" field could echo secrets
    # (e.g. a password that failed validation) back to the client and logs.
    fields = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    _log_error(422, "validation_error", f"{len(fields)} invalid field(s)")
    return JSONResponse(
        error_body("validation_error", "Request validation failed", fields), status_code=422
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered for StarletteHTTPException only
        raise exc
    code = STATUS_CODES.get(exc.status_code, "error")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    _log_error(exc.status_code, code, message)
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers for expected errors (unexpected ones: CatchAllMiddleware)."""
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)


class CatchAllMiddleware:
    """Turn any unhandled exception into a 500 standard body.

    Must sit INSIDE RequestContextMiddleware (see module docstring). If the
    response had already started streaming, nothing can be sent any more; the
    error is logged and the connection is closed by re-raising.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Full traceback to the log; the client only gets a generic message.
            log.exception("request.unhandled_exception")
            if started:
                raise
            response = JSONResponse(
                error_body("internal_error", "Unexpected error"), status_code=500
            )
            await response(scope, receive, send)
