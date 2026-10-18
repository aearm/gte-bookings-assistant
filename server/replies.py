"""How the API answers when something goes wrong ({"detail": plain English, "details": technical text})
and how it streams progress (Server-Sent Events: "event: <name>" and "data: <json>" per message)."""
import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from errors import details, friendly
from server.convert import plain

log = logging.getLogger("server")


class ApiError(Exception):
    """An answer other than 200, with a message for the person using the app."""

    def __init__(self, status: int, detail: str, details: str = ""):
        super().__init__(detail)
        self.status, self.detail, self.details = status, detail, details


def not_found(what: str) -> ApiError:
    return ApiError(404, f"{what} wasn't found. It may have been deleted, or the server restarted.")


def from_exception(exc: Exception, status: int = 400) -> ApiError:
    """A domain error (a query that failed, Claude unreachable...) in plain English, with the technical text."""
    return ApiError(status, friendly(exc), details(exc))


def error_body(detail: str, technical: str = "") -> dict:
    return {"detail": detail, **({"details": technical} if technical else {})}


def install(app: FastAPI) -> None:
    """Every error leaves the API as {"detail", "details"}."""

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(error_body(exc.detail, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        return JSONResponse(error_body(detail), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        problems = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ()) if p != 'body')}: {e.get('msg', '')}"
                             for e in exc.errors())
        return JSONResponse(error_body("Some of what was sent isn't valid. Check the fields and try again.", problems),
                            status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("Error in %s %s", request.method, request.url.path)
        return JSONResponse(error_body(friendly(exc), details(exc)), status_code=500)


# ---------------------------------------------------------------- Server-Sent Events --

def event(name: str, data) -> str:
    return f"event: {name}\ndata: {json.dumps(plain(data), ensure_ascii=False, separators=(',', ':'), allow_nan=False)}\n\n"


KEEP_ALIVE = ": keep-alive\n\n"  # a comment line: keeps proxies from closing a quiet stream


def stream(events) -> StreamingResponse:
    """An async iterator of event() texts as an SSE response (not cached, not buffered by proxies)."""
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
