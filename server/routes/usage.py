"""Usage (admins only): what Claude has cost, and how long and how much each recent question took."""
import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

import usage
from server.auth import require_admin
from server.convert import plain

router = APIRouter(tags=["usage"], dependencies=[Depends(require_admin)])
RECENT = 300


def week_summary(rows: list[dict]) -> dict:
    """(extra) The Usage page's four numbers: questions, median time, average cost and cost in 7 days."""
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    recent = [r for r in rows if r.get("time", "") >= week_ago]
    basis = recent or rows
    return {"questions_7d": len(recent),
            "median_seconds": statistics.median(r.get("seconds", 0) for r in basis) if basis else None,
            "average_cost": sum(r.get("cost", 0) for r in basis) / len(basis) if basis else None,
            "cost_7d": sum(r.get("cost", 0) for r in recent),
            "from_memory_7d": sum(1 for r in recent if r.get("memory"))}


@router.get("/usage")
def read_usage(days: int = 30) -> dict:
    """report = usage.cost_report (totals, by activity, by model, per day); recent = the latest questions,
    newest first."""
    questions = usage.load(kind="question")
    return plain({"report": usage.cost_report(days=max(1, min(days, 366))), "recent": list(reversed(questions[-RECENT:])),
                  "summary": week_summary(questions)})
