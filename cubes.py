"""The cubes (Analysis Services databases) the admin has connected, and where each one's files live.

Each cube has its own folder in models/: schema.md (structure), value_index.json (every value),
glossary.json (agreed meanings), notes.md (hints for Claude) and setup.json (setup questions).
In local mode there is a single "cube": the files in data/local. models/ holds company data and
is not in git."""
import json
import re
import shutil
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
    return {"enabled": [config.SSAS_DATABASE] if config.SSAS_DATABASE else []}


def enabled() -> list[str]:
    """The cubes people can use, in the admin's order. In local mode: just the local files."""
    if config.resolve_source() == "local":
        return [LOCAL]
    return _load().get("enabled", [])


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
        if not CUBES_FILE.exists():
            set_enabled([cube])
    for old, new in moves:
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))
