"""Signing in and out as admin (see server/auth.py for the cookie)."""
import asyncio

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

import secrets_store
from server import auth
from server.replies import ApiError
from server.schemas import FirstPassword, SessionState, SignIn

router = APIRouter(tags=["session"])
WRONG_PASSWORD_DELAY = 1.0  # seconds: slows down guessing
MIN_LENGTH = 8


@router.get("/session", response_model=SessionState)
def session(request: Request) -> dict:
    return {"admin": auth.is_admin(request), "has_admin_password": secrets_store.has_admin_password()}


@router.post("/session", response_model=SessionState)
async def sign_in(body: SignIn, request: Request, response: Response) -> dict:
    if not await run_in_threadpool(secrets_store.has_admin_password):
        raise ApiError(409, "No admin password has been created yet. Create one first.")
    if not await run_in_threadpool(secrets_store.check_admin_password, body.password):
        await asyncio.sleep(WRONG_PASSWORD_DELAY)
        raise ApiError(401, "That password isn't right. (Forgotten it? Run reset_admin_password.py on the server.)")
    auth.set_session(response, request, body.keep)
    return {"admin": True, "has_admin_password": True}


@router.delete("/session", response_model=SessionState)
def sign_out(request: Request, response: Response) -> dict:
    auth.clear_session(response, request)
    return {"admin": False, "has_admin_password": secrets_store.has_admin_password()}


@router.post("/session/first-password", response_model=SessionState)
def first_password(body: FirstPassword, request: Request, response: Response) -> dict:
    """Only while no admin password exists: creates it and signs in (kept, like the Streamlit app)."""
    if secrets_store.has_admin_password():
        raise ApiError(409, "An admin password already exists. Sign in with it, or change it on the Settings page.")
    if len(body.password) < MIN_LENGTH:
        raise ApiError(400, f"Use at least {MIN_LENGTH} characters.")
    secrets_store.set_admin_password(body.password)
    auth.set_session(response, request, keep=True)
    return {"admin": True, "has_admin_password": True}
