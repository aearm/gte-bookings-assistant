"""Admin sign-in for the API. Signing in sets the ba_session cookie: a token signed with the admin
password's hash (secrets_store.make_login_token), so changing the password signs every browser out.
"Keep me signed in" = a 30-day cookie; otherwise a cookie that ends with the browser session (and a
token that expires within a day anyway). The cookie is httpOnly (page scripts can't read it) and
SameSite=Strict; writes also need the X-Requested-With header, which other sites can't send."""
import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse

import secrets_store
from server.replies import ApiError, error_body

COOKIE = "ba_session"
KEEP_DAYS = 30
SESSION_DAYS = 1      # lifetime of the token in a browser-session cookie
CSRF_HEADER, CSRF_VALUE = b"x-requested-with", b"bookings-assistant"
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def is_admin(request: Request) -> bool:
    return secrets_store.check_login_token(request.cookies.get(COOKIE, ""))


def require_admin(request: Request) -> None:
    """Dependency for the routes only admins may use."""
    if not is_admin(request):
        raise ApiError(401, "Sign in as admin to do this.")


def set_session(response: Response, request: Request, keep: bool) -> None:
    token = secrets_store.make_login_token(KEEP_DAYS if keep else SESSION_DAYS)
    response.set_cookie(COOKIE, token, max_age=KEEP_DAYS * 86400 if keep else None, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")


def clear_session(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")


def kept(request: Request) -> bool:
    """Whether the current cookie is a "keep me signed in" one (its token lasts more than two days)."""
    expires = request.cookies.get(COOKIE, "").partition(".")[0]
    return expires.isdigit() and int(expires) - time.time() > 2 * 86400


class CsrfGuard:
    """Refuses writes (POST/PUT/PATCH/DELETE under /api) without X-Requested-With: bookings-assistant.
    A form or image on another site can't add that header, so it can't make a signed-in browser change
    anything here."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope["method"] in WRITES and scope["path"].startswith("/api/")
                and dict(scope["headers"]).get(CSRF_HEADER) != CSRF_VALUE):
            reply = JSONResponse(error_body("This request was refused: it didn't come from the app."), status_code=403)
            await reply(scope, receive, send)
            return
        await self.app(scope, receive, send)
