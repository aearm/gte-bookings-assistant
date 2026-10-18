"""The web server: the API under /api and the React app (web/dist) for every other path.

Run:  python start_api.py   (port 8600 next to the Streamlit app on 8501 until the switch-over)
The API is described in docs/api.md (and at /docs while the server runs). Start-up work (cube worker
processes, warm-up, the nightly chart runs) is in background.py.
"""
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:  # the domain modules (answering, dashboards...) live in the app folder
    sys.path.insert(0, str(BASE))

from server import auth, background, replies  # noqa: E402
from server.routes import (app_info, chat, cubes, dashboards, glossary, jobs, periods, session, settings,  # noqa: E402
                           usage)

WEB = BASE / "web" / "dist"
STARTED = time.time()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    background.start()
    try:
        yield
    finally:
        background.stop()


app = FastAPI(title="Bookings Assistant API", version=(BASE / "VERSION").read_text(encoding="utf-8").strip(),
              lifespan=lifespan)
app.add_middleware(auth.CsrfGuard)
app.add_middleware(GZipMiddleware, minimum_size=1024)  # results are JSON text: a tenth of the size zipped (not SSE)
replies.install(app)
for module in (session, app_info, chat, dashboards, periods, glossary, cubes, jobs, settings, usage):
    app.include_router(module.router, prefix="/api")


# ---------------------------------------------------------------- the React app --
# Built files (JS, CSS, fonts) are cached by the browser for good: their names change with every
# build. index.html is never cached, so a new version shows on the next reload.
if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    file = (WEB / path).resolve()
    if path and file.is_file() and WEB in file.parents:
        return FileResponse(file)
    index = WEB / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "The React app isn't built yet: cd web && npm run build"}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
