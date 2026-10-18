"""Settings. Values come from the .env file next to this script."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Where the data comes from:
#   auto  = live Analysis Services on Windows, local files on Mac/Linux
#   ssas  = live Analysis Services model (Windows only)
#   local = CSV / Excel files in data/local (any computer)
DATA_SOURCE = os.getenv("DATA_SOURCE", "auto").strip().lower() or "auto"
LOCAL_DATA_DIR = BASE_DIR / "data" / "local"


def resolve_source() -> str:
    """"ssas" (live cubes) or "local" (files in data/local)."""
    import platform
    if DATA_SOURCE in ("ssas", "local"):
        return DATA_SOURCE
    return "ssas" if platform.system() == "Windows" else "local"

# Analysis Services model (from Power BI > Data source settings)
SSAS_SERVER = os.getenv("SSAS_SERVER", "")
SSAS_DATABASE = os.getenv("SSAS_DATABASE", "")
# Login for the model. Leave SSAS_USERNAME blank to use your Windows login instead.
# The password is stored in Windows Credential Manager by set_password.py (safer than .env).
SSAS_USERNAME = os.getenv("SSAS_USERNAME", "").strip()
SSAS_PASSWORD = os.getenv("SSAS_PASSWORD", "")  # optional fallback; prefer set_password.py
KEYRING_SERVICE = "bookings-assistant-ssas"
# Extra connection-string parts, only if IT tells you to
SSAS_CONNECTION_EXTRA = os.getenv("SSAS_CONNECTION_EXTRA", "")
# Folder containing Microsoft.AnalysisServices.AdomdClient.dll (found automatically if blank)
ADOMD_PATH = os.getenv("ADOMD_PATH", "")

# Keys and passwords set on the app's Settings page are kept in Windows Credential Manager
# (macOS: Keychain), not in any file. A key in .env still works as a fallback.
APP_KEYRING_SERVICE = "bookings-assistant"


def stored_secret(name: str) -> str:
    try:
        import keyring
        return keyring.get_password(APP_KEYRING_SERVICE, name) or ""
    except Exception:
        return ""


# Claude API
_env_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_API_KEY = stored_secret("anthropic_api_key") or ("" if _env_api_key == "sk-ant-..." else _env_api_key)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
# How hard Claude thinks when planning a query (low / medium / high): medium is fast and accurate enough.
CLAUDE_PLAN_EFFORT = os.getenv("CLAUDE_PLAN_EFFORT", "medium")
# Fast, cheap model for simple jobs: picking the cubes a question needs, and formatting standard charts.
CLAUDE_FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-5-5")
# Model for building the data layer (once, after installation): it studies every cube, so it
# gets the most capable model; questions use CLAUDE_MODEL.
CLAUDE_LAYER_MODEL = os.getenv("CLAUDE_LAYER_MODEL", "claude-opus-5-5")

# Safety limit on rows pulled per question
MAX_ROWS = int(os.getenv("MAX_ROWS", "5000"))
# A step of a plan joined with other steps is never cut short (the join would add up part of the
# data); above this many rows it fails instead, and Claude aggregates it or narrows it with @KEYS.
STEP_MAX_ROWS = int(os.getenv("STEP_MAX_ROWS", "100000"))

# Files. Each cube has its own folder in models/ (structure, value index, glossary, notes, setup);
# see cubes.py. The single files below are from before several cubes were supported and are
# moved into the cube's folder the first time the app starts.
MODELS_DIR = BASE_DIR / "models"                # per cube folders, and data_layer/ (see data_layer.py)
# all dashboards and their charts (APP_DASHBOARDS_FILE: another file, e.g. for the end-to-end tests)
DASHBOARDS_FILE = Path(os.getenv("APP_DASHBOARDS_FILE") or BASE_DIR / "dashboards.json")
# the dashboards the app ships with (builtin_dashboards.py); 0 leaves them out (e.g. for tests)
BUILTIN_DASHBOARDS = os.getenv("APP_BUILTIN_DASHBOARDS", "1") != "0"
NOTES_TEMPLATE = BASE_DIR / "business_notes.example.md"
SCHEMA_FILE = BASE_DIR / "schema.md"            # (old) live model structure
LOCAL_SCHEMA_FILE = BASE_DIR / "schema_local.md"  # (old) structure of the local data files
NOTES_FILE = BASE_DIR / "business_notes.md"     # (old) your own hints for Claude
GLOSSARY_FILE = BASE_DIR / "glossary.json"      # (old) agreed meaning of each number
DASHBOARD_FILE = BASE_DIR / "dashboard.json"    # (old) the single dashboard
VALUE_INDEX_FILE = BASE_DIR / "data" / "value_index.json"  # (old) every value in the data
ENV_FILE = BASE_DIR / ".env"
QUERIES_DIR = BASE_DIR / "queries"              # saved .dax files for scheduled pulls
# usage, answer memory, history, saved dashboard numbers, decisions (APP_DATA_DIR: another folder, e.g. for
# the end-to-end tests, which must never change the real ones)
DATA_DIR = Path(os.getenv("APP_DATA_DIR") or BASE_DIR / "data")
RESULTS_DIR = DATA_DIR / "results"              # one CSV per question asked
SNAPSHOTS_DIR = DATA_DIR / "snapshots"          # output of pull.py
HISTORY_FILE = DATA_DIR / "history.jsonl"       # log of questions, DAX and result files
