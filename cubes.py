"""The cubes (Analysis Services databases) the admin has connected, and where each one's files live.

Each cube has its own folder in models/: schema.md (structure), value_index.json (every value),
glossary.json (agreed meanings), notes.md (hints for Claude) and setup.json (setup questions).
In local mode there is a single "cube": the files in data/local. models/ holds company data and
is not in git."""
import json
import re
import shutil
import threading
import time
from pathlib import Path

import config

LOCAL = "Local files"
CUBES_FILE = config.MODELS_DIR / "cubes.json"


def slug(cube: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", cube.lower()).strip("-") or "default"


def folder(cube: str) -> Path:
    path = config.MODELS_DIR / slug(cube)
    path.mkdir(parents=True, exist_ok=True)
    return path


def schema_file(cube: str) -> Path:
    return folder(cube) / "schema.md"


def index_file(cube: str) -> Path:
    return folder(cube) / "value_index.json"


def glossary_file(cube: str) -> Path:
    return folder(cube) / "glossary.json"


def notes_file(cube: str) -> Path:
    path = folder(cube) / "notes.md"
    if not path.exists() and config.NOTES_TEMPLATE.exists():
        shutil.copy(config.NOTES_TEMPLATE, path)
    return path


def setup_file(cube: str) -> Path:
    return folder(cube) / "setup.json"


def label(cube: str) -> str:
    """Short name for menus: 'Company - Bookings' -> 'Bookings'."""
    return cube.split(" - ", 1)[1] if " - " in cube else cube


# ---------------------------------------------------------------- which cubes are connected --

def _load() -> dict:
    if CUBES_FILE.exists():
        return json.loads(CUBES_FILE.read_text(encoding="utf-8"))
    return {}


# Until an admin picks the cubes, all of them are connected: every cube on the server with data. The
# server's list is asked in a thread of its own at most every 10 minutes, and a page waits for it a few
# seconds at most (while the server refreshes a cube it can hold new queries for minutes).
SERVER_SECONDS, SERVER_WAIT = 600, 5.0
_server: dict = {"time": 0.0, "names": None, "thread": None}
_server_lock = threading.Lock()


def _read_server() -> None:
    try:
        import ssas
        _server.update(names=sorted(str(n) for n in ssas.list_databases()["CATALOG_NAME"]), time=time.time())
    except Exception:
        _server["time"] = time.time() - SERVER_SECONDS + 60  # unreachable: ask again in a minute


def server_names(wait: float = SERVER_WAIT) -> list[str]:
    """Every cube on the server this login can open ([] when no server is set or it can't be reached)."""
    if not config.SSAS_SERVER:
        return []
    if time.time() - _server["time"] > SERVER_SECONDS:
        with _server_lock:
            asking = _server["thread"]
            if asking is None or not asking.is_alive():
                asking = _server["thread"] = threading.Thread(target=_read_server, name="server-cubes", daemon=True)
                asking.start()
        asking.join(wait)
    return list(_server["names"] or [])


def enabled() -> list[str]:
    """The cubes people can use, in the admin's order: all the server's cubes with data until an admin picks
    them on the Cubes page. In local mode: just the local files."""
    if config.resolve_source() == "local":
        return [LOCAL]
    picked = _load().get("enabled")
    if picked is not None:
        return picked
    import semantic
    everything = [c for c in server_names() if semantic.usable(c)]
    return everything or ([config.SSAS_DATABASE] if config.SSAS_DATABASE else [])


def set_enabled(names: list[str]) -> None:
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    data = _load()
    data["enabled"] = names
    CUBES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def default() -> str:
    names = enabled()
    return names[0] if names else ""


def is_ready(cube: str) -> bool:
    """True once the cube's structure has been read (it can answer questions)."""
    return (config.MODELS_DIR / slug(cube) / "schema.md").exists()


# ---------------------------------------------------------------- one-time move of old files --

def migrate() -> None:
    """Move files from the one-cube layout into the default cube's folder (runs once)."""
    moves = []
    if config.resolve_source() == "local":
        moves.append((config.LOCAL_SCHEMA_FILE, schema_file(LOCAL)))
    elif config.SSAS_DATABASE:
        cube = config.SSAS_DATABASE
        moves += [(config.SCHEMA_FILE, schema_file(cube)), (config.VALUE_INDEX_FILE, index_file(cube)),
                  (config.GLOSSARY_FILE, glossary_file(cube)),
                  (config.NOTES_FILE, folder(cube) / "notes.md")]
        if not CUBES_FILE.exists() and config.SCHEMA_FILE.exists():  # a one-cube install from before
            set_enabled([cube])
    for old, new in moves:
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))
