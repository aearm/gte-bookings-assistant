r"""Runs the web server (FastAPI + the React app) on port 8600 (API_PORT in .env, or --port).

Run:  .venv\Scripts\python.exe start_api.py           in this window (Ctrl+C stops it)
      .venv\Scripts\pythonw.exe start_api.py          in the background (output in data/api.log) - what
                                                      Windows starts automatically, see install/install_autostart.ps1
      start_api.py --open                             open the app in the browser: when it isn't running
                                                      yet, start it first (the Windows task if there is one)
"""
import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # see start_server.py

BASE = Path(__file__).resolve().parent
LOG = BASE / "data" / "api.log"
MAX_LOG_BYTES = 5_000_000
TASK = "Bookings Assistant"  # the Windows task that starts the app (install/install_autostart.ps1)


def task_from_settings() -> str:
    """The Windows task that starts this copy's web app (data/autostart.json, written by
    install/install_autostart.ps1); "" when none does - no task, or a task set up for the previous app."""
    try:
        import json
        saved = json.loads((BASE / "data" / "autostart.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    if not isinstance(saved, dict) or saved.get("app", "web") != "web":
        return ""
    return saved.get("task") or TASK


def port_from_settings() -> int:
    """API_PORT from the environment or .env, else 8600."""
    try:
        from dotenv import dotenv_values
        from_file = dotenv_values(BASE / ".env").get("API_PORT")
    except Exception:
        from_file = None
    return int(os.getenv("API_PORT") or from_file or 8600)


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_and_open(port: int, seconds: int = 120) -> bool:
    for _ in range(seconds * 2):
        if listening(port):
            webbrowser.open(f"http://localhost:{port}")
            return True
        time.sleep(0.5)
    return False


def _start_task(task: str) -> bool:
    """Start the Windows task that runs the app (when there is one). False: no task."""
    if os.name != "nt":
        return False
    hidden = 0x08000000  # CREATE_NO_WINDOW
    if subprocess.run(["schtasks", "/Query", "/TN", task], capture_output=True, creationflags=hidden).returncode:
        return False
    return subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True, creationflags=hidden).returncode == 0


def serve(port: int) -> int:
    os.chdir(BASE)
    sys.path.insert(0, str(BASE))
    if sys.stdout is None:  # pythonw: no console
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:  # keep one older log, start a new one
            LOG.replace(LOG.with_suffix(".old.log"))
        log = open(LOG, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=port, log_level="info", access_log=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bookings Assistant web server")
    parser.add_argument("--port", type=int, default=0, help="port (default: API_PORT in .env, else 8600)")
    parser.add_argument("--open", action="store_true", help="open the app in the browser, starting it if needed")
    parser.add_argument("--task", default="", help="the Windows task that starts it (for --open; default: this copy's)")
    args = parser.parse_args(argv)
    port = args.port or port_from_settings()
    if args.open:
        if listening(port):  # already running (e.g. started with Windows): just open it
            webbrowser.open(f"http://localhost:{port}")
            return 0
        task = args.task or task_from_settings()
        if task and _start_task(task):
            return 0 if _wait_and_open(port) else 1
        threading.Thread(target=_wait_and_open, args=(port,), daemon=True).start()
        if sys.stdout is not None:
            print(f"Starting Bookings Assistant on http://localhost:{port} ... your browser will open. "
                  "Keep this window open while using the app (Ctrl+C stops it).")
    return serve(port)


if __name__ == "__main__":
    sys.exit(main())
