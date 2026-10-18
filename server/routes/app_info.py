"""What the app is (version, data source, what can be asked about) and whether the server is up."""
import time

from fastapi import APIRouter

import answering
import config
import cube_setup
import cubes
import dashboards
import data_layer
import updates
from server import background, pool
from server.routes.periods import DEFAULTS
from server.schemas import Info

router = APIRouter(tags=["app"])
STARTED = time.time()


def scopes() -> list[dict]:
    """What Chat can be asked about: all the data (once the data layer is built), then each cube."""
    out = [{"value": "", "label": "All data"}] if data_layer.is_built() else []
    return out + [{"value": c, "label": data_layer.cube_label(c)} for c in cubes.enabled()]


def example_questions(scope: str = "") -> list[str]:
    if not scope:
        return data_layer.example_questions()
    return cube_setup.example_questions(scope) or data_layer.profile(scope).get("example_questions", [])


@router.get("/info", response_model=Info)
def info(scope: str = "") -> dict:
    """scope (extra): the example questions of one cube instead of all the data's."""
    ready, why = answering.ready(scope)
    if ready and not config.ANTHROPIC_API_KEY:
        ready, why = False, "No Claude API key is set yet, so questions can't be answered. An admin adds it on the Settings page."
    elif ready and config.resolve_source() == "ssas" and not config.SSAS_SERVER:
        ready, why = False, "No server is set yet. An admin adds it on the Settings page."
    return {"version": updates.current_version(), "data_source": config.resolve_source(), "ready": ready, "why": why,
            "scopes": scopes(), "example_questions": example_questions(scope)[:6], "defaults": DEFAULTS,
            "chart_types": [{"value": k, "label": v} for k, v in dashboards.TYPE_LABELS.items()]}


@router.get("/health")
def health() -> dict:
    """Is the server up, how long has it been running, and are the cube workers warm."""
    workers = pool.active()
    return {"ok": True, "version": updates.current_version(), "data_source": config.resolve_source(),
            "up_seconds": round(time.time() - STARTED),
            "workers": {"warm": (workers.warm if workers else True) and background.state["warm"],
                        "mode": "processes" if workers else "in-process",
                        "count": workers.workers if workers else 0,
                        "pids": workers.pids() if workers else []},
            "last_prerun": background.state["last_prerun"]}
