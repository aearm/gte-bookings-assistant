"""Answering a question from the data layer, shared by Chat and the dashboards:
question -> the cubes it needs (routing.py) -> plan (Claude, with those cubes' details, the values of
the question found in the data and verified examples) -> values checked -> run (each cube, joined) ->
one retry with the error if it fails. A scope of "" means all the data. Chat's ask() also reuses the
plan of a question already answered today (answer_memory.py)."""
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

import answer_memory
import cubes
import data_layer
import data_tools
import llm
import plans
import routing
import usage
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
    spec: dict = field(default_factory=dict)    # the chart and the written answer (ask())
    answer_id: int | None = None                # in answer_memory (to mark it verified)


def _pick(question, names, context, say) -> routing.Pick:
    """The cubes to give Claude in full: the one picked by the user, else a quick Haiku choice."""
    if len(names) == 1:
        return routing.Pick(list(names), "the cube picked", routing.value_hits(question, names))
    say("Picking the cubes that answer it")
    with usage.stage("route"):
        picked = routing.pick(question, names, context)
    usage.note(picked=picked.cubes)
    return picked


def _plan(question, names, scope, picked, context, clarification, instructions, failed=None, error=None,
          on_step=None):
    language = get_backend(names[0]).language
    details = [(c, data_layer.cube_details(c)) for c in picked.cubes]
    return llm.question_to_plan(question, routing.cards_text(), details, date.today().isoformat(), language,
                                context, failed_plan=failed, error=error, clarification=clarification,
                                instructions=instructions, hits=routing.hits_text(picked.hits, picked.cubes or None),
                                join=routing.join_path(picked.cubes), examples=answer_memory.examples(question, scope),
                                **data_tools.checks(names, on_step))


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
    picked = _pick(question, names, context, say)
    with usage.stage("plan"):
        result = _plan(question, names, scope, picked, context, clarification, instructions, on_step=say)
    if result.get("needs_clarification"):
        usage.note(outcome="clarify")
        return Outcome("clarify", result, question=result["clarifying_question"], options=result.get("options", [])[:4])
    if result.get("reuse_previous"):
        usage.note(outcome="reuse")
        return Outcome("reuse", result)
    plan = plans.Plan.from_dict(result)
    for attempt in (1, 2):
        try:
            plans.validate(plan, names)
            if needs_dates and not plan.uses_dates():
                raise ValueError("The plan does not use the dashboard dates. Filter the period with @START and @END.")
            say("Checking the values it filters on")
            with usage.stage("check"):
                plan, problems, notes = plans.check_values(plan)
            if problems:  # a value that isn't in the data: ask instead of returning nothing
                p = problems[0]
                usage.note(outcome="clarify")
                return Outcome("clarify", result, plan=plan, question=p.question(), options=p.suggestions)
            say("Pulling the data" + (f" from {len(plan.steps)} cubes and joining them" if not plan.single else ""))
            with usage.stage("query"):
                df = plans.run(plan.with_dates(*period) if period else plan)
            usage.note(outcome="data", cubes=plan.cubes, rows=len(df))
            return Outcome("data", result, plan=plan, df=df, notes=notes)
        except Exception as error:
            if attempt == 2:
                raise
            say("The query failed, asking Claude to fix it")
            usage.note(retried=True)
            with usage.stage("plan"):
                result = _plan(question, names, scope, picked, context, clarification, instructions,
                               failed=plan.text(), error=str(error)[:1500], on_step=say)
            plan = plans.Plan.from_dict(result)
    raise RuntimeError("unreachable")


def describe(question: str, df, chart_request: str, plan: plans.Plan | None) -> dict:
    """The chart (formatted for this data) and the written answer."""
    query = plan.text() if plan else ""
    return llm.describe_result(question, df, chart_request=chart_request, query=query,
                               measures=data_layer.measure_notes(plan.cubes if plan else [], query))


def ask(question: str, scope: str = ALL, context: list[dict] | None = None,
        clarification: tuple[str, str] | None = None, on_step=None, on_data=None) -> Outcome:
    """The whole answer for Chat: plan, data and chart, recorded in usage as one question.
    context = earlier answers (dicts with "question", "query", and for a redraw "df" and "plan").
    on_data(df) shows the numbers as soon as they arrive, before the chart is drawn."""
    say = on_step or (lambda text: None)
    with usage.track("question", question, scope=scope or "all"):
        if not context and not clarification:  # asked already today: rerun its plan, no Claude
            saved = answer_memory.same_day(question, scope)
            again = _rerun(question, saved, say) if saved else None
            if again:
                return again
        outcome = answer(question, scope, context, clarification, on_step=say)
        request = outcome.result.get("chart_request", "")
        if outcome.kind == "reuse":  # the same data, shown differently
            previous = (context or [{}])[-1]
            outcome.df = previous.get("df")
            outcome.plan = plans.Plan.from_dict(previous["plan"]) if previous.get("plan") else None
            request = request or question
        if outcome.df is not None and not outcome.df.empty:
            if on_data:
                on_data(outcome.df)
            say("Drawing the chart you asked for" if request else "Choosing the best chart")
            with usage.stage("chart"):
                outcome.spec = describe(question, outcome.df, request, outcome.plan)
        elif outcome.df is not None:
            outcome.spec = {"chart_type": "table", "title": "No results",
                            "summary": "The query ran but returned no rows. " + (
                                " ".join(outcome.notes) or "Try widening the filters or dates.")}
        if outcome.kind == "data" and outcome.plan is not None and not context and not clarification:
            outcome.answer_id = answer_memory.remember(question, scope, outcome.plan.to_dict(), outcome.result,
                                                       outcome.spec, outcome.df)
        return outcome


def _rerun(question: str, saved: dict, say) -> Outcome | None:
    """A question answered earlier today: run its saved plan again (fresh numbers). The chart and
    answer are reused when the numbers are the same, else redrawn. None if the plan no longer runs."""
    plan = plans.Plan.from_dict(saved["plan"])
    say("Asked earlier today: running the same plan for the latest numbers")
    try:
        with usage.stage("query"):
            df = plans.run(plan)
    except Exception:
        return None
    usage.note(outcome="data", cubes=plan.cubes, rows=len(df), memory="same_day")
    outcome = Outcome("data", saved["result"], plan=plan, df=df, answer_id=saved["id"])
    if answer_memory.data_hash(df) == saved["data_hash"]:
        outcome.spec = saved["spec"]
    elif df.empty:
        outcome.spec = {"chart_type": "table", "title": "No results",
                        "summary": "The query ran but returned no rows. Try widening the filters or dates."}
    else:
        with usage.stage("chart"):
            outcome.spec = describe(question, df, saved["result"].get("chart_request", ""), plan)
        answer_memory.update_spec(saved["id"], outcome.spec, df)
    return outcome


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
