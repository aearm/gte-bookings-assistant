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

# Safety limit on rows pulled per question
MAX_ROWS = int(os.getenv("MAX_ROWS", "5000"))

# Files
SCHEMA_FILE = BASE_DIR / "schema.md"            # live model structure (build_schema.py)
LOCAL_SCHEMA_FILE = BASE_DIR / "schema_local.md"  # structure of the local data files
NOTES_FILE = BASE_DIR / "business_notes.md"     # your own hints for Claude
GLOSSARY_FILE = BASE_DIR / "glossary.json"      # agreed meaning of each number (Glossary page)
ENV_FILE = BASE_DIR / ".env"
QUERIES_DIR = BASE_DIR / "queries"              # saved .dax files for scheduled pulls
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"              # one CSV per question asked
SNAPSHOTS_DIR = DATA_DIR / "snapshots"          # output of pull.py
HISTORY_FILE = DATA_DIR / "history.jsonl"       # log of questions, DAX and result files
