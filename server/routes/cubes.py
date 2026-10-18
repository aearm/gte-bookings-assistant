"""Cubes (admins only): which cubes people can ask about, the data layer built over them (a job), and
each cube's setup: read its structure, let Claude map its business words (jobs), answer the open
questions and confirm the rest. Same steps as views/cubes_page.py."""
import threading
import time

import pandas as pd
from fastapi import APIRouter, Depends

import config
import cube_setup
import cubes
import data_layer
import semantic
from backends import get_backend
from errors import friendly
from server import jobs
from server.auth import require_admin
from server.replies import ApiError, not_found
from server.schemas import EnabledCubes, JobStarted, LayerBuild, SetupAnswer, SetupConfirm, SetupSkip

router = APIRouter(tags=["cubes"], dependencies=[Depends(require_admin)])

SERVER_CUBES_SECONDS = 600
SERVER_CUBES_WAIT = 5.0  # seconds a page waits for the list: while a cube is being refreshed the server can
                         # hold new queries for a minute or more, and the page must not hang with it
_server_cubes: dict = {"time": 0.0, "rows": [], "error": None}
_listing: dict = {"thread": None}
_listing_lock = threading.Lock()


def _read_server_cubes() -> None:
    import ssas
    try:
        df = ssas.list_databases().sort_values("CATALOG_NAME")
        rows = []
        for _, row in df.iterrows():
            refreshed = pd.to_datetime(row["DATE_MODIFIED"], errors="coerce")
            rows.append({"name": str(row["CATALOG_NAME"]), "label": cubes.label(str(row["CATALOG_NAME"])),
                         "updated": f"{refreshed:%d %b %H:%M}" if pd.notna(refreshed) else ""})
        _server_cubes.update(time=time.time(), rows=rows, error=None)
    except Exception as exc:
        _server_cubes["error"] = exc


def server_cubes(fresh: bool = False, wait: float = SERVER_CUBES_WAIT) -> list[dict]:
    """Every cube on the server with when its data was refreshed (asked at most every 10 minutes). The
    server is asked in a thread of its own: when it takes longer than `wait` seconds the last list is
    used (the answer is kept for next time); with no list yet, an error says the server is busy."""
    if config.resolve_source() != "ssas":
        return []
    if fresh or time.time() - _server_cubes["time"] > SERVER_CUBES_SECONDS:
        with _listing_lock:
            listing = _listing["thread"]
            if listing is None or not listing.is_alive():
                _server_cubes["error"] = None
                listing = _listing["thread"] = threading.Thread(target=_read_server_cubes, name="server-cubes",
                                                                daemon=True)
                listing.start()
        listing.join(wait)
        if listing.is_alive():
            if not _server_cubes["rows"]:
                raise RuntimeError("The bookings server is busy (it may be refreshing a cube), so its list of "
                                   "cubes isn't here yet. Try again in a minute.")
        elif _server_cubes["error"] is not None:
            raise _server_cubes["error"]
    return _server_cubes["rows"]


def coverage(cube: str) -> str:
    cov = (semantic.cube(cube) or {}).get("coverage", {})
    return f"{cov['first']} to {cov.get('last', '?')}" if cov.get("first") else ""


def cubes_json(fresh: bool = False) -> dict:
    layer = data_layer.status()
    found, problem = [], ""
    try:
        found = server_cubes(fresh)
    except Exception as exc:
        problem = friendly(exc)
    decisions = semantic.decisions()
    return {
        "server_cubes": [c["name"] for c in found], "server_cubes_detail": found, "server_error": problem,
        "local": config.resolve_source() != "ssas", "server": config.SSAS_SERVER,
        "enabled": cubes.enabled(),
        "cubes": [{"name": c, "label": data_layer.cube_label(c), "ready": cubes.is_ready(c),
                   "setup": cube_setup.status_label(c), "usable": semantic.usable(c), "coverage": coverage(c),
                   "in_layer": c in layer["cubes"]} for c in cubes.enabled()],
        "layer": layer, "drift": semantic.drift(),
        "meaning": {"decisions": len(decisions), "agreed": sum(r.get("status") == "agreed" for r in decisions)},
        "layer_model": config.CLAUDE_LAYER_MODEL,
    }


def connected(cube: str) -> str:
    if cube not in cubes.enabled():
        raise not_found("This cube")
    return cube


@router.get("/cubes")
def list_cubes(fresh: bool = False) -> dict:
    """fresh (extra): ask the server for its cubes now instead of the list from the last 10 minutes."""
    return cubes_json(fresh)


@router.put("/cubes/enabled")
def set_enabled(body: EnabledCubes) -> dict:
    """The cubes people can use: the admin's existing order kept, new ones added at the end."""
    if config.resolve_source() != "ssas":
        raise ApiError(400, "Local mode: the only data source is the files in data/local.")
    available = {c["name"] for c in server_cubes(wait=30)}  # saving waits longer than a page
    unknown = [n for n in body.names if available and n not in available]
    if unknown:
        raise ApiError(400, "These cubes aren't on the server: " + ", ".join(unknown))
    current = cubes.enabled()
    cubes.set_enabled([c for c in current if c in body.names] + [c for c in body.names if c not in current])
    return cubes_json()


@router.post("/layer/build", response_model=JobStarted)
def build_layer(body: LayerBuild) -> dict:
    """Build (or update) the data layer: every cube read, Claude studies them. One build at a time."""
    names = body.cubes or None
    if names and any(n not in cubes.enabled() for n in names):
        raise ApiError(400, "Only connected cubes can go in the data layer.")

    def work(job):
        built = data_layer.build(names, only_changed=body.only_changed, on_progress=job.say)
        for cube, problem in (built.get("errors") or {}).items():
            job.say(f"Left out of the data layer - {cubes.label(cube)}: {problem}")
        job.say(f"Data layer ready: {len(built.get('cubes', {}))} cube(s), {len(built.get('entities', []))} shared dimension(s)")
        return {"cubes": list(built.get("cubes", {})), "errors": built.get("errors", {})}
    return {"job": jobs.start("layer_build", work, single=True).id}


# ---------------------------------------------------------------- one cube's setup --

def setup_json(cube: str) -> dict:
    data = cube_setup.load(cube)
    backend = get_backend(cube)
    read = ""
    if backend.schema_file.exists():
        read = pd.Timestamp(backend.schema_file.stat().st_mtime, unit="s").strftime("%d %b %H:%M")
    return {
        "cube": cube, "label": data_layer.cube_label(cube), "status": cube_setup.status_label(cube),
        "progress": cube_setup.progress(cube), "structure_read": read, "summary": data.get("summary", ""),
        "drafted": data.get("drafted", ""),
        "questions": [{"index": i, "term": it.get("term", ""), "question": it.get("question", ""),
                       "options": it.get("options", [])} for i, it in cube_setup.open_items(data, "question")],
        "proposals": [{"index": i, "term": it.get("term", ""), "meaning": it.get("meaning", ""),
                       "in_data": it.get("in_data", "")} for i, it in cube_setup.open_items(data, "proposal")],
    }


@router.get("/cubes/{cube}/setup")
def setup_state(cube: str) -> dict:
    return setup_json(connected(cube))


@router.post("/cubes/{cube}/setup/read", response_model=JobStarted)
def read_structure(cube: str) -> dict:
    """(extra) Step 1: read the cube's structure and values again (about a minute for a large cube)."""
    connected(cube)

    def work(job):
        job.say(f"Reading {cubes.label(cube)}...")
        job.say(get_backend(cube).refresh_schema())
    return {"job": jobs.start(f"read:{cube}", work, single=True).id}


@router.post("/cubes/{cube}/setup/draft", response_model=JobStarted)
def draft(cube: str) -> dict:
    """Step 2: Claude reads the structure and drafts the map of business words (about a minute)."""
    connected(cube)
    if not cubes.is_ready(cube):
        raise ApiError(400, "Read the cube's structure first.")

    def work(job):
        job.say("Claude is reading the cube and drafting the map...")
        data = cube_setup.draft(cube)
        job.say(data.get("summary", "") or "Map drafted.")
    return {"job": jobs.start(f"draft:{cube}", work, single=True).id}


def item_index(cube: str, index: int, state: str) -> int:
    items = dict(cube_setup.open_items(cube_setup.load(cube), state))
    if index not in items:
        raise ApiError(400, "That item has been answered already, or doesn't exist.")
    return index


@router.post("/cubes/{cube}/setup/answer")
def answer(cube: str, body: SetupAnswer) -> dict:
    connected(cube)
    item = cube_setup.load(cube)["items"][item_index(cube, body.index, "question")]
    if body.option is not None:
        if not 0 <= body.option < len(item.get("options", [])):
            raise ApiError(400, "That option doesn't exist.")
        cube_setup.answer(cube, body.index, option=body.option)
    elif body.custom.strip():
        cube_setup.answer(cube, body.index, custom=body.custom)
    else:
        raise ApiError(400, "Pick an option or describe it in your words.")
    return setup_json(cube)


@router.post("/cubes/{cube}/setup/skip")
def skip(cube: str, body: SetupSkip) -> dict:
    connected(cube)
    cube_setup.skip(cube, item_index(cube, body.index, "question"))
    return setup_json(cube)


@router.post("/cubes/{cube}/setup/confirm")
def confirm(cube: str, body: SetupConfirm) -> dict:
    connected(cube)
    proposals = dict(cube_setup.open_items(cube_setup.load(cube), "proposal"))
    if any(i not in proposals for i in body.indexes + body.rejected):
        raise ApiError(400, "Some of these items have been confirmed already, or don't exist.")
    cube_setup.confirm(cube, body.indexes, body.rejected)
    return setup_json(cube)
