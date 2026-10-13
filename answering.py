"""Answering a question from the data layer, shared by Chat and the dashboards:
question -> plan (Claude, after checking the data) -> values checked -> run (each cube, joined) ->
one retry with the error if it fails. A scope of "" means all the data: Claude picks the cubes."""
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import cubes
import data_layer
import data_tools
import llm
import plans
import value_check
from backends import get_backend

ALL = ""  # scope: every cube in the data layer


def cubes_in(scope: str = ALL) -> list[str]:
    """The cubes a question may use: the one picked, or every cube in the data layer (before the
    layer is built: every cube that has been read)."""
    if scope:
        return [scope]
    return data_layer.layer_cubes() or [c for c in cubes.enabled() if cubes.is_ready(c)]


def ready(scope: str = ALL) -> tuple[bool, str]:
    """(can answer, why not)."""
    if not cubes.enabled():
        return False, "No cube is connected yet. An admin connects cubes on the Cubes page."
    if scope == ALL and not data_layer.is_built():
        return False, "The data layer hasn't been built yet. An admin builds it once on the Cubes page."
    if scope and not cubes.is_ready(scope):
        return False, "This cube hasn't been read yet. An admin builds the data layer on the Cubes page."
    return True, ""


@dataclass
class Outcome:
    kind: str                                   # "data", "clarify" or "reuse"
    result: dict = field(default_factory=dict)  # Claude's plan (understanding, explanation, chart_request...)
    plan: plans.Plan | None = None
    df: pd.DataFrame | None = None
    notes: list[str] = field(default_factory=list)
    question: str = ""                          # clarify: the question to ask
    options: list[str] = field(default_factory=list)


def _plan(question, names, scope, context, clarification, instructions, failed=None, error=None, on_step=None):
    catalog = data_layer.catalog_text(only=None if scope == ALL else names)
    details = data_layer.cube_details(names[0]) if len(names) == 1 else ""
    language = get_backend(names[0]).language
    return llm.question_to_plan(question, catalog, details, "", date.today().isoformat(), language, context,
                                failed_plan=failed, error=error, clarification=clarification,
                                instructions=instructions, **data_tools.checks(names, on_step))


def answer(question: str, scope: str = ALL, context: list[dict] | None = None,
           clarification: tuple[str, str] | None = None, instructions: str = "",
           period: tuple[date, date] | None = None, needs_dates: bool = False, on_step=None) -> Outcome:
    """Plan, check and run. period fills @START/@END (dashboard charts); needs_dates = every step
    must use them. on_step(text) reports progress."""
    say = on_step or (lambda text: None)
    names = cubes_in(scope)
    if not names:
        raise RuntimeError("No cube is set up yet. An admin builds the data layer on the Cubes page.")
    say("Understanding the question")
    result = _plan(question, names, scope, context, clarification, instructions, on_step=say)
    if result.get("needs_clarification"):
        return Outcome("clarify", result, question=result["clarifying_question"], options=result.get("options", [])[:4])
    if result.get("reuse_previous"):
        return Outcome("reuse", result)
    plan = plans.Plan.from_dict(result)
    for attempt in (1, 2):
        try:
            plans.validate(plan, names)
            if needs_dates and not plan.uses_dates():
                raise ValueError("The plan does not use the dashboard dates. Filter the period with @START and @END.")
            say("Checking the values it filters on")
            plan, problems, notes = plans.check_values(plan)
            if problems:  # a value that isn't in the data: ask instead of returning nothing
                p = problems[0]
                return Outcome("clarify", result, plan=plan, question=p.question(), options=p.suggestions)
            say("Pulling the data" + (f" from {len(plan.steps)} cubes and joining them" if not plan.single else ""))
            df = plans.run(plan.with_dates(*period) if period else plan)
            return Outcome("data", result, plan=plan, df=df, notes=notes)
        except Exception as error:
            if attempt == 2:
                raise
            say("The query failed, asking Claude to fix it")
            result = _plan(question, names, scope, context, clarification, instructions,
                           failed=plan.text(), error=str(error)[:1500], on_step=say)
            plan = plans.Plan.from_dict(result)
    raise RuntimeError("unreachable")


def require_values(outcome: Outcome) -> Outcome:
    """For dashboards: a value that isn't in the data is an error (only the person asking can say
    which real value they mean)."""
    if outcome.kind == "clarify":
        if outcome.plan is not None:
            raise value_check.ValueProblem(f"{outcome.question} Options: {', '.join(outcome.options)}. "
                                           "Change the question to use a real value.")
        raise RuntimeError(f"Claude needs more detail: {outcome.question} "
                           + (f"(e.g. {', '.join(outcome.options)})" if outcome.options else ""))
    return outcome
