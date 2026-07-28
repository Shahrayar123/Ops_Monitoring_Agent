"""Consistent error responses + request IDs.

Every error leaves the API in the same JSON envelope, so the frontend has ONE
error shape to handle:

    { "error": { "code": "not_found", "message": "...", "request_id": "..." } }

Every request gets an X-Request-ID (echoed back if the client sent one), and
unhandled exceptions are logged with that id — so a user-reported error can be
matched to the exact stack trace in the logs.
"""

import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import log_context

log = logging.getLogger("backend")
access_log = logging.getLogger("backend.access")

# HTTP status -> stable machine-readable code the frontend can switch on.
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}


def _envelope(status: int, message, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": _STATUS_CODES.get(status, "error"),
                "message": message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


class ApiError(HTTPException):
    """Raise anywhere in a route to produce a clean enveloped error."""


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        # Set BEFORE the route runs, so every log line for this request — ours,
        # the engine's, SQLAlchemy's — carries it, not just the two lines below.
        # get_current_user (api/deps.py) fills in user_id/email once auth runs,
        # so the "completed" line below is user-attributed but "started" isn't.
        log_context.set_request_id(request.state.request_id)

        started = time.monotonic()
        access_log.info("%s %s started", request.method, request.url.path)
        response = await call_next(request)
        duration_ms = round((time.monotonic() - started) * 1000, 1)

        # Starlette runs the route in a separate task (see api/deps.py's comment),
        # so re-read the user identity from request.state — the shared object —
        # rather than the contextvar, which this (middleware) task never saw
        # get_current_user's update. Re-set it so THIS log line is attributed too.
        log_context.set_user(getattr(request.state, "user_id", None), getattr(request.state, "user_email", None))
        access_log.info(
            "%s %s -> %s in %sms", request.method, request.url.path, response.status_code, duration_ms,
            extra={"status_code": response.status_code, "duration_ms": duration_ms},
        )

        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return _envelope(exc.status_code, exc.detail, request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # Compact the pydantic error list into readable "field: problem" lines.
        problems = [
            f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}"
            for e in exc.errors()
        ]
        return _envelope(422, "; ".join(problems), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception(
            "Unhandled error [%s] %s %s", request.state.request_id, request.method, request.url.path
        )
        return _envelope(500, "Something went wrong on our side — it has been logged.", request)
