"""Settings: the Claude API key, the cube server login, the admin password, and app updates. Keys and
passwords go to Windows Credential Manager (secrets_store) and are never sent back: the status says
only whether each one is set."""
import asyncio
import threading
import time

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

import config
import llm
import secrets_store
import updates
from errors import details, friendly
from server import auth
from server.auth import require_admin
from server.replies import ApiError, from_exception
from server.routes.session import MIN_LENGTH, WRONG_PASSWORD_DELAY
from server.schemas import AdminPassword, ApiKey, Ok, ServerLogin

router = APIRouter(tags=["settings"])
admin = [Depends(require_admin)]


def status(request: Request) -> dict:
    """What is set, never the values (the username only for a signed-in admin)."""
    is_admin = auth.is_admin(request)
    where = secrets_store.api_key_status()
    server = {"address": config.SSAS_SERVER, "database": config.SSAS_DATABASE,
              "login_saved": secrets_store.server_password_saved(), "windows_login": not config.SSAS_USERNAME}
    if is_admin:
        server["username"] = config.SSAS_USERNAME
    return {"api_key": "missing" if where == "missing" else "set", "api_key_where": where,
            "server": server, "admin_password_set": secrets_store.has_admin_password(),
            "data_source": config.resolve_source(),
            "models": {"questions": config.CLAUDE_MODEL, "fast": config.CLAUDE_FAST_MODEL,
                       "layer": config.CLAUDE_LAYER_MODEL}}


@router.get("/settings")
def read_settings(request: Request) -> dict:
    return status(request)


@router.put("/settings/api-key", dependencies=admin)
def save_api_key(body: ApiKey, request: Request) -> dict:
    key = body.key.strip()
    if not key.startswith("sk-ant-"):
        raise ApiError(400, "That doesn't look like a Claude API key. They start with sk-ant-.")
    secrets_store.save_api_key(key)
    return status(request)


@router.post("/settings/api-key/test", dependencies=admin)
def test_api_key() -> dict:
    """Asks Claude's API about the model (uses no tokens)."""
    try:
        llm.check_connection()
    except Exception as exc:
        return {"ok": False, "model": config.CLAUDE_MODEL, "detail": friendly(exc), "details": details(exc)}
    return {"ok": True, "model": config.CLAUDE_MODEL}


@router.put("/settings/server", dependencies=admin)
def save_server(body: ServerLogin, request: Request) -> dict:
    server = body.server.strip()
    username = config.SSAS_USERNAME if body.username is None else body.username.strip()
    if not server:
        raise ApiError(400, "Enter the server.")
    if username and username != config.SSAS_USERNAME and not body.password:
        raise ApiError(400, "Enter the password for the new username too.")
    secrets_store.save_server_address(server, config.SSAS_DATABASE if body.database is None else body.database.strip())
    secrets_store.save_server_login(username, body.password)
    return status(request)


@router.post("/settings/server/test", dependencies=admin)
def test_server() -> dict:
    """(extra) Connects to the server and counts the cubes this login can open."""
    if config.resolve_source() != "ssas":
        raise ApiError(400, "The app is using local data files, so no server is needed.")
    import ssas
    try:
        found = ssas.list_databases()
    except Exception as exc:
        raise from_exception(exc) from exc
    return {"ok": True, "cubes": len(found)}


@router.put("/settings/admin-password", response_model=Ok, dependencies=admin)
async def change_admin_password(body: AdminPassword, request: Request, response: Response) -> dict:
    """The new password signs every other browser out; this one gets a new cookie."""
    if not await run_in_threadpool(secrets_store.check_admin_password, body.current):
        await asyncio.sleep(WRONG_PASSWORD_DELAY)
        raise ApiError(400, "The current password isn't right.")
    if len(body.new) < MIN_LENGTH:
        raise ApiError(400, f"Use at least {MIN_LENGTH} characters.")
    keep = auth.kept(request)
    await run_in_threadpool(secrets_store.set_admin_password, body.new)
    auth.set_session(response, request, keep)
    return {"ok": True}


# ---------------------------------------------------------------- updates --

CHECK_SECONDS = 300
_latest: dict = {"time": 0.0, "release": None, "error": ""}


def latest(fresh: bool = False):
    """The newest release on GitHub (asked at most every 5 minutes unless fresh). Raises if unreachable."""
    if fresh or time.time() - _latest["time"] > CHECK_SECONDS:
        _latest.update(time=time.time(), release=updates.latest_release())
    return _latest["release"]


@router.get("/updates", dependencies=admin)
def check_updates(fresh: bool = False) -> dict:
    """status: updating | up_to_date | available | no_release | check_failed."""
    out = {"current": updates.current_version(), "latest": "", "published": "", "notes": "", "page": "",
           "developer_copy": updates.is_developer_copy(), "last": updates.last_status(),
           "error": _latest["error"]}  # a download that failed after Update was pressed
    if updates.updating():
        return {**out, "status": "updating"}
    try:
        release = latest(fresh)
    except Exception as exc:
        return {**out, "status": "check_failed", "error": friendly(exc)}
    if release is None:
        return {**out, "status": "no_release"}
    out.update(latest=release.version, published=release.published, notes=release.notes, page=release.page)
    return {**out, "status": "available" if release.is_newer() else "up_to_date"}


@router.post("/updates/apply", dependencies=admin)
def apply_update() -> dict:
    """Downloads the newest version and starts the updater, which stops the app, updates it (keeping every
    setting and data file, with a backup) and starts it again."""
    if updates.updating():
        raise ApiError(409, "An update is running already.")
    if updates.is_developer_copy():
        raise ApiError(400, "This folder is a developer copy (git), so it's updated with git pull and a restart, "
                            "not from here.")
    try:
        release = latest(fresh=True)
    except Exception as exc:
        raise from_exception(exc) from exc
    if release is None or not release.is_newer():
        raise ApiError(400, "There is no newer version to install.")

    _latest["error"] = ""

    def run():
        try:
            updates.launch(updates.download(release), release.version, server="start_api.py")
        except Exception as exc:
            _latest.update(error=friendly(exc))
    threading.Thread(target=run, name="update", daemon=True).start()
    return {"started": True, "version": release.version}
