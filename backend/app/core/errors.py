"""Consistent error responses + request IDs.

Every error leaves the API in the same JSON envelope, so the frontend has ONE
error shape to handle:

    { "error": { "code": "not_found", "message": "...", "request_id": "..." } }

Every request gets an X-Request-ID (echoed back if the client sent one), and
unhandled exceptions are logged with that id — so a user-reported error can be
matched to the exact stack trace in the logs.
"""

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("backend")

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
        response = await call_next(request)
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
