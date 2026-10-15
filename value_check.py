"""Checks the text values a query filters on (e.g. Status Name = "Confirmed") against the real data
before it runs. A guessed value matches nothing and silently returns no rows; instead the user is
asked which real value they mean. Differences in capitals are fixed automatically."""
import difflib
import re
from dataclasses import dataclass, field

DAX_COL = r"'(?:[^']|'')+'\[[^\]]+\]"
DAX_STR = r'"(?:[^"]|"")*"'
SQL_COL = r'"[^"]+"'
SQL_STR = r"'(?:[^']|'')*'"


@dataclass
class Problem:
    column: str               # as written in the query, e.g. 'Booking Status'[Status Name]
    value: str                # the value that is not in the data
    suggestions: list[str] = field(default_factory=list)

    def question(self) -> str:
        return f'"{self.value}" isn\'t a value of {column_label(self.column)}. Which do you mean?'


@dataclass
class CheckResult:
    query: str                                        # with capitals corrected where needed
    problems: list[Problem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)    # e.g. a value that exists but has no data


def column_label(col: str) -> str:
    m = re.match(r"'((?:[^']|'')+)'\[([^\]]+)\]", col)
    return f"{m.group(1)} › {m.group(2)}" if m else col.strip('"')


def _unquote_list(text: str, language: str) -> list[str]:
    if language == "DAX":
        return [v.replace('""', '"') for v in re.findall(r'"((?:[^"]|"")*)"', text)]
    return [v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", text)]


def filters(query: str, language: str) -> list[tuple[str, list[str]]]:
    """(column, [values]) for every equality / IN filter on a text value in the query."""
    found = []
    if language == "DAX":
        for m in re.finditer(rf"({DAX_COL})\s*(?:==|=|<>)\s*({DAX_STR})", query):
            found.append((m.group(1), _unquote_list(m.group(2), language)))
        for m in re.finditer(rf"({DAX_STR})\s*(?:==|=|<>)\s*({DAX_COL})", query):
            found.append((m.group(2), _unquote_list(m.group(1), language)))
        for m in re.finditer(rf"({DAX_COL})\s+IN\s*\{{([^{{}}]*)\}}", query, flags=re.IGNORECASE):
            found.append((m.group(1), _unquote_list(m.group(2), language)))
        for m in re.finditer(rf"TREATAS\s*\(\s*\{{([^{{}}()]*)\}}\s*,\s*({DAX_COL})\s*\)", query, flags=re.IGNORECASE):
            found.append((m.group(2), _unquote_list(m.group(1), language)))
    else:
        for m in re.finditer(rf"({SQL_COL})\s*(?:=|<>|!=)\s*({SQL_STR})", query):
            found.append((m.group(1), _unquote_list(m.group(2), language)))
        for m in re.finditer(rf"({SQL_COL})\s+(?:NOT\s+)?IN\s*\(([^()]*)\)", query, flags=re.IGNORECASE):
            found.append((m.group(1), _unquote_list(m.group(2), language)))
    return [(col, vals) for col, vals in found if vals]


def schema_columns(schema_text: str) -> dict[str, dict]:
    """Column -> {type, group_with, values (full list or None), no_data} from schema.md."""
    info = {}
    pattern = rf"^- ({DAX_COL}|{SQL_COL}) \(([^)]*)\)(.*)$"
    for line in schema_text.splitlines():
        m = re.match(pattern, line)
        if not m:
            continue
        col, col_type, rest = m.groups()
        group_with = []
        if "| group with " in rest:
            group_with = re.findall(DAX_COL, rest.split("| group with ", 1)[1].split(" | ")[0])
        values, no_data = None, set()
        if "| values: " in rest:
            part = rest.split("| values: ", 1)[1]
            items = re.findall(r'"((?:[^"]|"")*)"(?: \(([^)]*)\))?', part)
            values = [v.replace('""', '"') for v, _ in items]
            no_data = {v.replace('""', '"') for v, n in items if n == "no data"}
        info[col] = {"type": col_type, "group_with": group_with, "values": values, "no_data": no_data}
    return info


def _is_text(col_type: str) -> bool:
    return col_type.split()[0].upper() in ("TEXT", "VARCHAR", "STRING") if col_type else False


def _suggest(meta: dict, column: str, value: str, backend) -> list[str]:
    if backend.index.indexed(column):
        hits = [h["value"] for h in backend.index.search(value, column=column, limit=12) if h["count"]]
        if hits:
            return hits[:6]
    if meta["values"] is None:
        try:
            return backend.search_values(column, meta["group_with"], value)
        except Exception:
            return []
    with_data = [v for v in meta["values"] if v not in meta["no_data"]] or meta["values"]
    low = value.lower().strip()
    words = [v for v in with_data if re.search(rf"\b{re.escape(low)}", v.lower()) or
             re.search(rf"\b{re.escape(v.lower())}\b", low)]
    close = difflib.get_close_matches(low, [v.lower() for v in with_data], n=6, cutoff=0.6)
    close = [next(v for v in with_data if v.lower() == c) for c in close]
    ordered = list(dict.fromkeys(words + close))
    if len(ordered) < 2 and len(with_data) <= 8:  # a short list: just offer it all
        ordered = list(dict.fromkeys(ordered + with_data))
    return ordered[:6]


def check(query: str, language: str, schema_text: str, backend) -> CheckResult:
    info = schema_columns(schema_text)
    result = CheckResult(query)
    for column, values in filters(query, language):
        meta = info.get(column)
        if not meta or not _is_text(meta["type"]):
            continue
        lookup = backend.index.lookup(column, values)  # the cube's value index: instant, covers long lists
        if lookup is not None:
            pass
        elif meta["values"] is not None:
            real = {v.lower().strip(): v for v in meta["values"]}
            lookup = {v: real.get(v.lower().strip()) for v in values}
        else:
            try:
                lookup = backend.find_values(column, meta["group_with"], values)
            except Exception:
                continue  # can't check this column; let the query run
        for value, actual in lookup.items():
            if actual is None:
                result.problems.append(Problem(column, value, _suggest(meta, column, value, backend)))
            elif actual != value and language == "SQL":  # SQL compares capitals exactly: use the real value
                quote = lambda v: "'" + v.replace("'", "''") + "'"
                result.query = result.query.replace(quote(value), quote(actual))
            if actual and (actual in meta["no_data"] or backend.index.has_no_data(column, actual)):
                result.notes.append(f'Nothing in the data has {column_label(column)} "{actual}".')
    return result


class ValueProblem(RuntimeError):
    """A query filters on a value that is not in the data (message is written for users)."""
