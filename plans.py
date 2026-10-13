"""Query plans: how a question is answered from one cube, or from several cubes joined.

A plan has one step per cube (a DAX query, or SQL on local files) and, when there are several
steps, combine_sql: one DuckDB SELECT that joins the steps' results by their names. Each cube is
its own Analysis Services database, so this is how numbers from different cubes meet (a federated
query): every step runs on its own cube, in parallel, and the results are joined in memory.

Stored on dashboards as chart["plan"] = {"steps": [...], "combine_sql": "..."}; charts from before
plans existed have a single chart["query"] on chart["cube"] and still work."""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

import duckdb
import pandas as pd

import config
import value_check
from backends import get_backend

MAX_STEPS = 5


@dataclass
class Step:
    name: str
    cube: str
    query: str


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    combine_sql: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        steps, seen = [], set()
        for i, s in enumerate(data.get("steps", [])):
            name = _table_name(s.get("name") or f"step{i + 1}")
            while name in seen:
                name += "_2"
            seen.add(name)
            steps.append(Step(name, s.get("cube", ""), s.get("query", "")))
        return cls(steps, (data.get("combine_sql") or "").strip() if len(steps) > 1 else "")

    @classmethod
    def from_chart(cls, chart: dict) -> "Plan":
        if chart.get("plan"):
            return cls.from_dict(chart["plan"])
        return cls([Step("result", chart.get("cube", ""), chart.get("query", ""))])

    def to_dict(self) -> dict:
        return {"steps": [{"name": s.name, "cube": s.cube, "query": s.query} for s in self.steps],
                "combine_sql": self.combine_sql}

    @property
    def cubes(self) -> list[str]:
        return list(dict.fromkeys(s.cube for s in self.steps))

    @property
    def single(self) -> bool:
        return len(self.steps) == 1

    def text(self) -> str:
        """The plan as one readable text (shown under answers, given to Claude as context)."""
        if self.single:
            return self.steps[0].query
        parts = [f"-- Step {s.name}: cube \"{s.cube}\"\n{s.query.strip()}" for s in self.steps]
        parts.append(f"-- Combine the steps (SQL)\n{self.combine_sql.strip()}")
        return "\n\n".join(parts)

    def with_dates(self, start: date, end: date) -> "Plan":
        """@START / @END replaced with the period (each step in its own query language)."""
        steps = []
        for s in self.steps:
            backend = get_backend(s.cube)
            steps.append(Step(s.name, s.cube, s.query.replace("@START", backend.date_literal(start))
                                                     .replace("@END", backend.date_literal(end))))
        return Plan(steps, self.combine_sql)

    def uses_dates(self) -> bool:
        return all("@START" in s.query and "@END" in s.query for s in self.steps)


def _table_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", str(text).lower()).strip("_") or "step"
    return name if not name[0].isdigit() else f"s_{name}"


# ---------------------------------------------------------------- checking --

def validate(plan: Plan, allowed_cubes: list[str] | None = None) -> None:
    """Raises if the plan can't be run as it is (unknown cube, no query, a bad combine step)."""
    if not plan.steps:
        raise RuntimeError("Claude did not return a query. Try rephrasing the question.")
    if len(plan.steps) > MAX_STEPS:
        raise ValueError(f"The plan has {len(plan.steps)} steps; at most {MAX_STEPS} cubes can be combined.")
    for s in plan.steps:
        if allowed_cubes is not None and s.cube not in allowed_cubes:
            raise ValueError(f"Step {s.name} uses the cube \"{s.cube}\", which is not one of the connected cubes: "
                             + ", ".join(f'"{c}"' for c in allowed_cubes))
        if not s.query.strip():
            raise ValueError(f"Step {s.name} has no query.")
    if not plan.single:
        if not plan.combine_sql:
            raise ValueError("The plan has several steps but no combine_sql to join them.")
        _validate_select(plan.combine_sql)


def _validate_select(sql: str) -> None:
    body = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL).strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", body, flags=re.IGNORECASE):
        raise ValueError("combine_sql is not a SELECT statement, so it was not run.")
    if ";" in body:
        raise ValueError("combine_sql contains more than one statement, so it was not run.")


def check_values(plan: Plan) -> tuple[Plan, list[value_check.Problem], list[str]]:
    """Every text value each step filters on, checked against its cube's data (see value_check).
    Returns (plan with capitals corrected, problems, notes)."""
    steps, problems, notes = [], [], []
    for s in plan.steps:
        backend = get_backend(s.cube)
        result = value_check.check(s.query, backend.language, backend.schema_text(), backend)
        steps.append(Step(s.name, s.cube, result.query))
        problems += result.problems
        notes += result.notes
    return Plan(steps, plan.combine_sql), problems, notes


# ---------------------------------------------------------------- running --

def run(plan: Plan, max_rows: int | None = None) -> pd.DataFrame:
    """Run every step (in parallel, each on its cube) and join them. Errors name the failing step."""
    max_rows = max_rows or config.MAX_ROWS
    if plan.single:
        s = plan.steps[0]
        return get_backend(s.cube).run(s.query, max_rows)

    def one(s: Step) -> pd.DataFrame:
        try:
            return get_backend(s.cube).run(s.query, max_rows)
        except Exception as exc:
            raise StepError(f"Step {s.name} (cube \"{s.cube}\") failed: {exc}") from exc
    workers = min(4, len(plan.steps)) if config.resolve_source() == "ssas" else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        frames = dict(zip([s.name for s in plan.steps], pool.map(one, plan.steps)))
    return combine(frames, plan.combine_sql, max_rows)


class StepError(RuntimeError):
    """A step of a plan failed (the message names it, for Claude to fix)."""


def combine(frames: dict[str, pd.DataFrame], sql: str, max_rows: int | None = None) -> pd.DataFrame:
    """Join the steps' results with combine_sql in a private in-memory database that can't read
    files or the network."""
    _validate_select(sql)
    con = duckdb.connect(":memory:")
    try:
        for name, df in frames.items():
            con.register("_frame", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _frame')
            con.unregister("_frame")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        try:
            cur = con.execute(sql.strip().rstrip(";"))
        except duckdb.Error as exc:
            shapes = "; ".join(f"{n}: " + ", ".join(f'"{c}"' for c in df.columns) for n, df in frames.items())
            raise StepError(f"combine_sql failed: {exc}\nThe steps returned these columns - {shapes}") from exc
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows) if max_rows else cur.fetchall()
    finally:
        con.close()
    return pd.DataFrame(rows, columns=columns)
