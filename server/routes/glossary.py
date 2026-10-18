"""Glossary and decisions: what the business words mean in a cube (everyone reads, admins edit), and
the meaning layer's questions only a person can answer (admins agree to an answer)."""
from fastapi import APIRouter, Depends

import cube_setup
import cubes
import data_layer
import glossary
import semantic
from server.auth import require_admin
from server.replies import ApiError, not_found
from server.schemas import DecisionAnswer, GlossaryRows

router = APIRouter(tags=["glossary"])


def connected(cube: str) -> str:
    if cube not in cubes.enabled():
        raise not_found("This cube")
    return cube


def glossary_json(cube: str) -> dict:
    rows, updated = glossary.load(cube)
    rows = [{c: r.get(c, "") for c in glossary.COLUMNS} for r in rows]
    return {"cube": cube, "label": data_layer.cube_label(cube), "summary": cube_setup.load(cube).get("summary", ""),
            "rows": rows, "updated": updated, "drafts": sum(r.get("Status") != "Agreed" for r in rows),
            "columns": glossary.COLUMNS, "statuses": glossary.STATUSES}


@router.get("/glossary/{cube}")
def read_glossary(cube: str) -> dict:
    return glossary_json(connected(cube))


@router.put("/glossary/{cube}", dependencies=[Depends(require_admin)])
def save_glossary(cube: str, body: GlossaryRows) -> dict:
    """Claude uses the new definitions from the next question."""
    glossary.save(connected(cube), body.rows)
    return glossary_json(cube)


def decision_json(r: dict) -> dict:
    return {"id": r["id"], "cube": r.get("cube", ""), "question": r.get("question", ""), "why": r.get("why", ""),
            "options": list(dict.fromkeys([*r.get("options", []), r.get("proposed", "")])),
            "proposed": r.get("proposed", ""), "answer": r.get("answer", r.get("proposed", "")),
            "status": "agreed" if r.get("status") == "agreed" else "proposed"}


@router.get("/decisions")
def decisions(cube: str = "") -> dict:
    """open = decisions still waiting for a person, across all cubes; items = this cube's (or all)."""
    every = semantic.decisions()
    return {"open": sum(r.get("status") != "agreed" for r in every),
            "items": [decision_json(r) for r in every if not cube or r.get("cube") == cube]}


@router.post("/decisions/{item_id}", dependencies=[Depends(require_admin)])
def decide(item_id: str, body: DecisionAnswer) -> dict:
    """An admin's answer: it wins over the proposed one and survives updates."""
    if not any(r["id"] == item_id for r in semantic.decisions()):
        raise not_found("This decision")
    if not body.answer.strip():
        raise ApiError(400, "Choose an answer.")
    semantic.save_decision(item_id, body.answer.strip())
    return decision_json(next(r for r in semantic.decisions() if r["id"] == item_id))
