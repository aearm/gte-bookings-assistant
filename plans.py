"""Query plans: how a question is answered from one cube, or from several cubes joined.

A plan has one step per cube (a DAX query, or SQL on local files) and, when there are several
steps, combine_sql: one DuckDB SELECT that joins the steps' results by their names. Each cube is
its own Analysis Services database, so this is how numbers from different cubes meet (a federated
query): every step runs on its own cube, in parallel, and the results are joined in memory.

Stored on dashboards as chart["plan"] = {"steps": [...], "combine_sql": "..."}; charts from before
plans existed have a single chart["query"] on chart["cube"] and still work."""
import difflib
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

import duckdb
import pandas as pd

import config
import cubes
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
        """@START / @END replaced with the period (each step in its own query language); @LAST (the
        period's last day, for a plan that filters "<= last day") too."""
        def fill(query: str, literal) -> str:
            return (query.replace("@START", literal(start)).replace("@END", literal(end))
                    .replace("@LAST", literal(end - timedelta(days=1))))
        steps = [Step(s.name, s.cube, fill(s.query, get_backend(s.cube).date_literal)) for s in self.steps]
        return Plan(steps, fill(self.combine_sql, _sql_date) if self.combine_sql else "")

    def uses_dates(self) -> bool:
        return all("@START" in s.query and "@END" in s.query for s in self.steps)

    def with_periods(self, spans: list[tuple[date, date]]) -> "Plan":
        """A chart's own periods filled in: @P1_START, @P1_LAST and @P1_END become the first period's
        first day, last day and the day after it; @P2_... the second period's (spans = (start, end
        exclusive) per period)."""
        def fill(query: str, literal) -> str:
            def one(m):
                n, edge = int(m.group(1)), m.group(2)
                if not 1 <= n <= len(spans):
                    raise ValueError(f"The query uses {m.group(0)}, but the chart has {len(spans)} period(s).")
                start, end = spans[n - 1]
                return literal({"START": start, "LAST": end - timedelta(days=1), "END": end}[edge])
            return OWN_PLACEHOLDER.sub(one, query)
        steps = [Step(s.name, s.cube, fill(s.query, get_backend(s.cube).date_literal)) for s in self.steps]
        return Plan(steps, fill(self.combine_sql, _sql_date) if self.combine_sql else "")

    def own_periods(self) -> int:
        """How many periods of its own the plan has placeholders for (@P1_..., @P2_...)."""
        found = [int(n) for s in self.steps for n, _ in OWN_PLACEHOLDER.findall(s.query)]
        found += [int(n) for n, _ in OWN_PLACEHOLDER.findall(self.combine_sql)]
        return max(found, default=0)


def _sql_date(d: date) -> str:
    """A date in the SQL that joins the steps (DuckDB)."""
    return f"DATE '{d.isoformat()}'"


OWN_PLACEHOLDER = re.compile(r"@P(\d+)_(START|LAST|END)\b")


# A step can keep only the members another step returned: @KEYS(top, Code) becomes the list of that
# step's "Code" values ({"1042", "2051"} in DAX, ('1042', '2051') in SQL) when that step has run. So a
# "top 10 customers with their searches" plan asks the second cube about 10 customers, not all of them.
_KEYS = re.compile(r"@KEYS\(\s*([A-Za-z_]\w*)\s*,\s*([^)]+?)\s*\)")


def waits_for(step: Step) -> set[str]:
    return {_table_name(name) for name, _ in _KEYS.findall(step.query)}


def _keys_literal(values: list, language: str) -> str:
    values = [v for v in dict.fromkeys(values) if v is not None and v == v]
    if not values:
        values = ["@none@"]  # matches nothing, keeps the query valid
    numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
    if language == "DAX":
        items = [str(v) if numbers else '"' + str(v).replace('"', '""') + '"' for v in values]
        return "{" + ", ".join(items) + "}"
    items = [str(v) if numbers else "'" + str(v).replace("'", "''") + "'" for v in values]
    return "(" + ", ".join(items) + ")"


def _with_keys(step: Step, frames: dict[str, pd.DataFrame]) -> Step:
    """The step with every @KEYS(...) replaced by the values the step it names returned."""
    language = get_backend(step.cube).language

    def values(m):
        name, column = _table_name(m.group(1)), m.group(2).strip().strip("\"'[]")
        df = frames[name]
        match = next((c for c in df.columns if str(c).lower() == column.lower()), None)
        if match is None:
            raise StepError(f"Step {step.name} uses @KEYS({m.group(1)}, {column}), but step {name} returned no "
                            f"column {column!r}; its columns are: " + ", ".join(f'"{c}"' for c in df.columns))
        return _keys_literal(df[match].tolist(), language)
    return Step(step.name, step.cube, _KEYS.sub(values, step.query))


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
        import semantic
        off = semantic.hidden(s.cube)
        used = [m for m in dict.fromkeys(re.findall(r"\[[^\]]+\]", s.query)) if m in off]
        if used:  # helpers, duplicates, broken or empty measures (the cube's meaning layer)
            raise ValueError(f"Step {s.name} uses {', '.join(used)}, which must not be used in \"{s.cube}\" ("
                             + "; ".join(f"{m}: {off[m]}" for m in used) + "). Use the measures its meaning layer lists.")
        others = {o.name for o in plan.steps if o is not s}
        if waits_for(s) - others:
            raise ValueError(f"Step {s.name} uses @KEYS of {', '.join(sorted(waits_for(s) - others))}, which is not "
                             "another step of the plan. Write @KEYS(<another step's name>, <its result column>).")
        unknown = unknown_names(s)
        if unknown:  # a misspelt or made-up name: Claude fixes it from the suggestion instead of the server failing
            raise ValueError(f"Step {s.name} uses names that are not in the cube \"{s.cube}\": " + "; ".join(unknown)
                             + ". Use only the exact names in the cube's details.")
    if not plan.single:
        if not plan.combine_sql:
            raise ValueError("The plan has several steps but no combine_sql to join them.")
        _validate_select(plan.combine_sql)


_QUALIFIED = re.compile(r"'((?:[^']|'')+)'\[([^\]]+)\]|\b([A-Za-z_]\w*)\[([^\]]+)\]")
_DEFINED = re.compile(r"\b(?:MEASURE|COLUMN)\s+(?:'(?:[^']|'')+'|\w+)\[([^\]]+)\]|\bTABLE\s+(\w+)\s*=", re.IGNORECASE)
_KEY_PART = re.compile(r"\.(UniqueName|Key\d+|Name)$", re.IGNORECASE)


@lru_cache(maxsize=64)
def _cube_names(cube: str, _changed: float) -> tuple[frozenset, frozenset, frozenset, frozenset]:
    """(tables, (table, column) pairs, column names, measure names) of a cube, lower case."""
    import semantic
    schema = semantic.parse_schema(get_backend(cube).schema_text() or "")
    pairs = set()
    for c in schema["columns"]:
        for ref in [c["column"], *c["group_with"], c["sort_by"]]:
            if m := _QUALIFIED.fullmatch(ref.strip()):
                pairs.add(((m.group(1) or "").replace("''", "'").lower(), m.group(2).lower()))
    measures = frozenset(m["name"].strip("[]").lower() for m in schema["measures"])
    return frozenset(t for t, _ in pairs), frozenset(pairs), frozenset(c for _, c in pairs), measures


def unknown_names(step: Step) -> list[str]:
    """Tables, columns and measures a DAX step uses that its cube doesn't have, each with the closest
    real name. Labels the query gives its own columns ("Bookings", then ORDER BY [Bookings]) and names
    it defines (DEFINE MEASURE ...) are fine. Empty when the cube's structure isn't known."""
    backend = get_backend(step.cube)
    path = cubes.schema_file(step.cube)
    if backend.language != "DAX" or not path.exists():
        return []
    tables, pairs, column_names, measures = _cube_names(step.cube, path.stat().st_mtime)
    if not pairs:
        return []
    body = re.sub(r"(--|//).*?$", "", step.query, flags=re.MULTILINE)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    labels = {t.replace('""', '"').lower(): t.replace('""', '"') for t in re.findall(r'"((?:[^"]|"")*)"', body)}
    body = re.sub(r'"(?:[^"]|"")*"', '""', body)
    defined = {(a or "").lower() for a, _ in _DEFINED.findall(body)} - {""}
    defined_tables = {(b or "").lower() for _, b in _DEFINED.findall(body)} - {""}
    real = {f"'{t}'[{c}]": (t, c) for t, c in pairs}
    problems = []
    for m in _QUALIFIED.finditer(body):
        table = (m.group(1) or "").replace("''", "'") if m.group(1) is not None else m.group(3)
        column = m.group(2) if m.group(1) is not None else m.group(4)
        t, c = table.lower(), column.lower()
        if t in defined_tables or c in measures or c in defined or (t, c) in pairs or (t, _KEY_PART.sub("", c)) in pairs:
            continue
        near = difflib.get_close_matches(f"'{t}'[{c}]", list(real), n=1, cutoff=0.6)
        problems.append(f"'{table}'[{column}]" + (f" (did you mean {_display(near[0], step.cube)}?)" if near else ""))
    import semantic
    allowed = [m for m in measures if f"[{m}]" not in {h.lower() for h in semantic.hidden(step.cube)}]
    for name in re.findall(r"\[([^\]]+)\]", _QUALIFIED.sub(" ", body)):
        n = name.lower()
        if n in measures or n in labels or n in defined or n in column_names:
            continue
        near = difflib.get_close_matches(n, allowed + sorted(labels), n=1, cutoff=0.6)
        shown = near and (f"[{labels[near[0]]}]" if near[0] in labels else _display(f"[{near[0]}]", step.cube))
        problems.append(f"[{name}]" + (f" (did you mean {shown}?)" if near else ""))
    return list(dict.fromkeys(problems))


def _display(lower_name: str, cube: str) -> str:
    """A name as the cube writes it (the checks compare in lower case)."""
    import semantic
    schema = semantic.parse_schema(get_backend(cube).schema_text() or "")
    names = [m["name"] for m in schema["measures"]] + [c["column"] for c in schema["columns"]]
    return next((n for n in names if n.lower() == lower_name), lower_name)


_DATE_LITERAL = re.compile(r"\bDATE\s*\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)|\bDATE\s*'(\d{4})-(\d{2})-(\d{2})'",
                           re.IGNORECASE)


def _dates_in(query: str) -> set:
    """The dates a query filters on (DATE(2026,9,1) or DATE '2026-09-01'); None for an impossible one."""
    found = set()
    for m in _DATE_LITERAL.finditer(query):
        y, mo, d = (g for g in m.groups() if g is not None)
        try:
            found.add(date(int(y), int(mo), int(d)))
        except ValueError:
            found.add(None)
    return found


def check_periods(plan: Plan, periods: list) -> None:
    """Raises when a step filters on dates and none of them is a first or last day of the question's
    periods (worked out by code, see rewrite.py): the plan counted another period. In a comparison, each
    period must be in the plan. Steps that filter by month names or years instead of dates aren't checked."""
    if not periods:
        return
    edges = set()
    for p in periods:
        edges |= {p.start, p.end - timedelta(days=1), p.end}
    every = {d for s in plan.steps for d in _dates_in(s.query) if d}
    if every and len(periods) > 1:  # a comparison: each of its periods must be in the plan
        for p in periods:
            inside = any(p.start <= d <= p.end for d in every)
            spanned = min(every) <= p.start and max(every) >= p.end - timedelta(days=1)
            if not inside and not spanned:
                raise ValueError(f"The plan filters no dates of {p.text()}, one of the periods the question compares "
                                 "(worked out from today's date). Include every period.")
    for s in plan.steps:
        found = _dates_in(s.query)
        if found and not found & edges:
            shown = ", ".join(sorted(d.isoformat() for d in found if d)) or "an impossible date"
            raise ValueError(f"Step {s.name} filters on {shown}, but the question's period"
                             f"{'s are' if len(periods) > 1 else ' is'} "
                             + "; ".join(p.text() for p in periods)
                             + " (worked out from today's date). Filter exactly from the first to the last day given.")


# ---------------------------------------------------------------- periods as placeholders --
# A chat answer goes on a dashboard without asking Claude again: each of its periods' dates in the plan
# becomes a placeholder that is filled in whenever the chart runs. How a date is used tells which edge
# of a period it is: ">= d" a first day, "<= d" a last day, "< d" the day after the last, "= d" or a
# date in a list a single day; BETWEEN d1 AND d2 and DATESBETWEEN(col, d1, d2) a first and a last day.

class CannotParametrize(ValueError):
    """A plan whose periods can't be found or told apart in its dates (Claude has to rewrite it)."""


def _date_of(m) -> date | None:
    y, mo, d = (int(g) for g in m.groups() if g is not None)
    try:
        return date(y, mo, d)
    except ValueError:
        return None


_LITERAL_TEXT = (r"(?:\bDATE\s*\(\s*\d{4}\s*,\s*\d{1,2}\s*,\s*\d{1,2}\s*\)|\bDATE\s*'\d{4}-\d{2}-\d{2}'"
                 r"|@(?:P\d+_)?(?:START|LAST|END)\b)")  # a date, or a placeholder for one
_BETWEEN_SECOND = re.compile(rf"\bBETWEEN\s*{_LITERAL_TEXT}\s*AND$", re.IGNORECASE)
_DATESBETWEEN_FIRST = re.compile(r"\bDATESBETWEEN\s*\(\s*[^,()]+,$", re.IGNORECASE)
_DATESBETWEEN_SECOND = re.compile(rf"\bDATESBETWEEN\s*\(\s*[^,()]+,\s*{_LITERAL_TEXT}\s*,$", re.IGNORECASE)


def _edge_role(text: str, m) -> str:
    """How the date literal m is used in text: "start", "last", "end" (the day after the last), "day"
    (a single day, or not said) or "after" (> d: no placeholder means that)."""
    before, after = text[:m.start()].rstrip()[-400:], text[m.end():].lstrip()
    for ending, role in ((">=", "start"), ("<=", "last"), ("<>", "day"), ("!=", "day"), ("<", "end"),
                         (">", "after")):
        if before.endswith(ending):
            return role
    if re.search(r"\bBETWEEN$", before, re.IGNORECASE) or _DATESBETWEEN_FIRST.search(before):
        return "start"
    if _BETWEEN_SECOND.search(before) or _DATESBETWEEN_SECOND.search(before):
        return "last"
    for starting, role in (("<=", "start"), (">=", "last"), ("<>", "day"), ("<", "after"), (">", "end")):
        if after.startswith(starting):
            return role
    return "day"


def _edge_for(d: date, role: str, spans: list[tuple[date, date]]) -> tuple[int, str] | None:
    """(period number, "START" / "LAST" / "END") that the date d used as role is, or None. A date whose use
    doesn't say (= d, a list, VAR x = d) is a first or last day, else the day after a period."""
    for i, (start, end) in enumerate(spans, start=1):
        if role in ("start", "day") and d == start:
            return i, "START"
        if role in ("last", "day") and d == end - timedelta(days=1):
            return i, "LAST"
        if role == "end" and d == end:
            return i, "END"
    if role == "day":
        return next(((i, "END") for i, (_, end) in enumerate(spans, start=1) if d == end), None)
    return None


def parametrize(plan: Plan, spans: list[tuple[date, date]], stems: list[str]) -> Plan:
    """The plan with its periods' dates replaced by placeholders: for period i, stems[i] + START (first
    day), LAST (last day) or END (the day after the last), e.g. "@P1_" -> @P1_START, or "@" -> the
    dashboard's @START / @LAST / @END. Dates that aren't in any period stay as they are. Raises
    CannotParametrize when a period has no date in the plan, a date inside a period isn't one of its
    edges, or a period's date is written as text (then only Claude can rewrite it)."""
    found: set[int] = set()

    def near(d: date) -> bool:  # in a period, or the day just before or after it
        return any(start - timedelta(days=1) <= d <= end for start, end in spans)

    def replace(text: str) -> str:
        def one(m):
            d = _date_of(m)
            if d is None:
                return m.group(0)
            role = _edge_role(m.string, m)
            edge = _edge_for(d, role, spans) if role != "after" else None
            if edge is None:
                if near(d):
                    raise CannotParametrize(f"The query uses {d.isoformat()} in a way that can't be moved with its period.")
                return m.group(0)
            found.add(edge[0])
            return stems[edge[0] - 1] + edge[1]
        for text_date in re.findall(r"['\"][^'\"\n]*?(\d{4}-\d{2}-\d{2})", _DATE_LITERAL.sub("", text)):
            try:
                d = date.fromisoformat(text_date)
            except ValueError:
                continue
            if near(d):
                raise CannotParametrize(f"The query writes the date {text_date} as text, so it can't be moved with its period.")
        return _DATE_LITERAL.sub(one, text)

    steps = [Step(s.name, s.cube, replace(s.query)) for s in plan.steps]
    combine = replace(plan.combine_sql) if plan.combine_sql else ""
    missing = [i for i in range(1, len(spans) + 1) if i not in found]
    if missing:
        raise CannotParametrize("The query has no dates of period " + ", ".join(map(str, missing))
                                + " (it may filter by month names or years instead).")
    return Plan(steps, combine)


_ANY_PLACEHOLDER = re.compile(r"@(?:P(\d+)_)?(START|LAST|END)\b")


def filters_a_range(plan: Plan, period: int = 0) -> bool:
    """Whether the plan filters a period (0 = the dashboard's @START...; 1 = @P1_...) as a range from its
    first day (>= START) to its last (<= LAST or < END) and never as single days (= START): only then can
    it show a period of another length, like the dashboard's."""
    starts = ends = 0
    for text in [s.query for s in plan.steps] + [plan.combine_sql]:
        for m in _ANY_PLACEHOLDER.finditer(text):
            if int(m.group(1) or 0) != period:
                continue
            role, edge = _edge_role(text, m), m.group(2)
            if role != {"START": "start", "LAST": "last", "END": "end"}[edge]:
                return False
            starts += edge == "START"
            ends += edge != "START"
    return starts > 0 and ends > 0


def rename_placeholders(plan: Plan, old: str, new: str) -> Plan:
    """Placeholders moved from one stem to another: "@P1_" -> "@" makes a chart's own first period
    follow the dashboard (@P1_START -> @START), "@" -> "@P1_" the other way round."""
    pattern = re.compile(re.escape(old) + r"(START|LAST|END)\b" if old != "@" else r"@(START|LAST|END)\b")

    def move(text: str) -> str:
        return pattern.sub(lambda m: new + m.group(1), text)
    return Plan([Step(s.name, s.cube, move(s.query)) for s in plan.steps], move(plan.combine_sql))


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
        return _run_step(plan.steps[0], max_rows)

    def one(s: Step) -> pd.DataFrame:
        try:
            df = _run_step(s, config.STEP_MAX_ROWS + 1)
        except StepError:
            raise
        except Exception as exc:
            raise StepError(f"Step {s.name} (cube \"{s.cube}\") failed: {exc}") from exc
        if len(df) > config.STEP_MAX_ROWS:  # never join part of a step: the totals would be wrong
            raise StepError(f"Step {s.name} (cube \"{s.cube}\") returned more than {config.STEP_MAX_ROWS:,} rows, "
                            "so it was not joined. Aggregate it to the grain of the answer, or keep only the "
                            "members another step picked with @KEYS.")
        return df
    workers = min(4, len(plan.steps)) if config.resolve_source() == "ssas" else 1
    frames, waiting = {}, list(plan.steps)
    while waiting:  # in rounds: the steps whose @KEYS steps have run, in parallel
        ready = [s for s in waiting if waits_for(s) <= set(frames)]
        if not ready:
            raise StepError("These steps wait for each other's @KEYS: " + ", ".join(s.name for s in waiting))
        with ThreadPoolExecutor(max_workers=min(workers, len(ready))) as pool:
            frames.update(zip([s.name for s in ready], pool.map(one, [_with_keys(s, frames) for s in ready])))
        waiting = [s for s in waiting if s not in ready]
    return combine(frames, plan.combine_sql, max_rows)


def _run_step(s: Step, max_rows: int | None) -> pd.DataFrame:
    try:
        return get_backend(s.cube).run(_with_needed_columns(s), max_rows)
    except Exception as exc:
        import semantic
        hint = semantic.composite_key_hint(s.cube, str(exc))
        if hint:  # the server's error names the column; this says what goes with it and how to filter it
            raise StepError(f"Step {s.name} (cube \"{s.cube}\") failed: {exc}{hint}") from exc
        raise


def _with_needed_columns(s: Step) -> str:
    """A DAX step with the helper columns its cube requires next to every grouped column (composite keys)."""
    backend = get_backend(s.cube)
    if backend.language != "DAX":
        return s.query
    import semantic
    return semantic.add_needed_columns(s.query, semantic.needed_columns(s.cube))


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
