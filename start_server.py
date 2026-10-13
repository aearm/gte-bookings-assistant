"""Runs the app in the background (no window) - what Windows starts automatically, see
install_autostart.ps1. Output goes to data/app.log. Open the app at http://localhost:8501.

Run:  .venv\\Scripts\\pythonw.exe start_server.py
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "data" / "app.log"
MAX_LOG_BYTES = 5_000_000


def main() -> int:
    os.chdir(BASE)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:  # keep one older log, start a new one
        LOG.replace(LOG.with_suffix(".old.log"))
    log = open(LOG, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log  # pythonw has no console; Streamlit's messages go to the log
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(BASE / "app.py"), "--server.headless", "true", "--server.port", "8501"]
    return cli.main()


if __name__ == "__main__":
    sys.exit(main())
