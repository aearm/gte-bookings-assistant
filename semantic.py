"""The meaning layer ("semantic layer"): what every measure, date and breakdown of the cubes means, one
official measure per business term, default dates, what to hide, data coverage, the cubes' query
rules and named business filters. Code enforces it; Claude reads it before answering.

It ships with the app in semantic/ (JSON, versioned with the code):
  semantic/cubes/<cube>.json   one file per cube: measures, dates, breakdowns, filters, rules
  semantic/terms.json          business term -> the one measure that answers it, and date words -> date role
  semantic/review.json         decisions only a person can make, with the proposed answer
  semantic/manifest.json       version and the cube structure it was built from
Admins' own decisions (Settings / Glossary review) are kept apart, in data/semantic_overrides.json,
so an update never overwrites them.

Facts are read from the cubes by code (no AI): `python semantic.py facts` writes
models/semantic_facts/<cube>.json - every measure with whether it has data, every date column with
the months it has data for, every breakdown with the helper columns it needs and its values."""
import json
import re
import sys
from datetime import date
from pathlib import Path

import config
import cubes

SEMANTIC_DIR = config.BASE_DIR / "semantic"
FACTS_DIR = config.MODELS_DIR / "semantic_facts"


# ---------------------------------------------------------------- reading the cube structure --

_MEASURE = re.compile(r"^- (\[[^\]]+\])\s+\(in '([^']*)'\)(.*)$")
_COLUMN = re.compile(r"^- ('(?:[^']|'')+'\[[^\]]+\]) \(([^)]*)\)(.*)$")


def parse_schema(text: str) -> dict:
    """The cube structure file (models/<cube>/schema.md) as data: measures and columns with their
    group-with helper columns, sort-by column, value count and listed values."""
    measures, columns = [], []
    for line in text.splitlines():
        if m := _MEASURE.match(line):
            rest = m.group(3)
            fmt = re.search(r"\| format: ([^|]+)", rest)
            formula = re.search(r"\| formula: (.+)$", rest)
            desc = re.search(r"^ - ([^|]+)", rest)
            measures.append({"name": m.group(1), "group": m.group(2),
                             "format": fmt.group(1).strip() if fmt else "",
                             "formula": formula.group(1).strip() if formula else "",
                             "description": desc.group(1).strip() if desc else ""})
        elif m := _COLUMN.match(line):
            rest = m.group(3)
            group_with = re.search(r"\| group with ([^|]+)", rest)
            sort_by = re.search(r"\| sort by ([^|]+)", rest)
            count = re.search(r"\| ([\d,]+) values", rest)
            listed = re.search(r"\| values: (.+)$", rest)
            values = re.findall(r'"((?:[^"]|"")*)" \(([^)]*)\)', listed.group(1)) if listed else []
            columns.append({
                "column": m.group(1), "type": m.group(2),
                "group_with": re.findall(r"'(?:[^']|'')+'\[[^\]]+\]", group_with.group(1)) if group_with else [],
                "sort_by": sort_by.group(1).strip() if sort_by else "",
                "distinct": int(count.group(1).replace(",", "")) if count else len(values) or None,
                "values": [{"value": v.replace('""', '"'), "data": n} for v, n in values],
            })
    return {"measures": measures, "columns": columns}


# ---------------------------------------------------------------- facts from the data --

def _run(cube: str, query: str):
    from backends import get_backend
    return get_backend(cube).run(query, None)


def _dax_date(d: date) -> str:
    return f"DATE({d.year},{d.month},{d.day})"


def measure_activity(cube: str, measures: list[str], date_column: str, today: date | None = None) -> dict:
    """{measure: {"all_time": total or None, "last_12_months": total or None}} - which measures have data
    at all, and recently (on the cube's main date). Asked in chunks so one broken measure can't hide
    the others."""
    today = today or date.today()
    start = today.replace(year=today.year - 1, day=1)
    end = today.replace(day=1)
    out = {}
    for i in range(0, len(measures), 25):
        chunk = measures[i:i + 25]
        cols = ", ".join(f'"m{j}", {m}' for j, m in enumerate(chunk))
        recent = (f"CALCULATETABLE(ROW({cols}), KEEPFILTERS(FILTER(ALL({date_column}), {date_column} >= "
                  f"{_dax_date(start)} && {date_column} < {_dax_date(end)})))")
        for key, query in (("all_time", f"EVALUATE ROW({cols})"), ("last_12_months", f"EVALUATE {recent}")):
            try:
                row = _run(cube, query).iloc[0].tolist()
            except Exception as exc:
                row = [None] * len(chunk)
                for m in chunk:
                    out.setdefault(m, {})[f"{key}_error"] = str(exc).splitlines()[0][:200]
            for m, v in zip(chunk, row):
                found = out.setdefault(m, {})
                try:
                    found[key] = None if v is None or v != v else float(v)
                except (TypeError, ValueError):  # a broken calculated measure answers with an error text
                    found[key] = None
                    found[f"{key}_error"] = str(v)[:200]
    return out


def date_coverage(cube: str, date_column: str, measure: str) -> dict:
    """The months a date column has data for (of one measure): first, last, and the recent months."""
    try:
        df = _run(cube, f'EVALUATE SUMMARIZECOLUMNS({date_column}, "v", {measure})')
    except Exception as exc:
        return {"error": str(exc).splitlines()[0][:200]}
    import pandas as pd
    if df.empty:
        return {"first": None, "last": None, "months": {}}
    days = pd.to_datetime(df.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(df.iloc[:, -1], errors="coerce").fillna(0)
    monthly = values[values != 0].groupby(days[values != 0].dt.to_period("M")).sum()
    if monthly.empty:
        return {"first": None, "last": None, "months": {}}
    return {"first": str(monthly.index.min()), "last": str(monthly.index.max()),
            "months_with_data": int(len(monthly)),
            "last_24_months": {str(k): round(float(v), 2) for k, v in monthly.items()
                               if str(k) >= f"{date.today().year - 2}-{date.today().month:02d}"}}


def build_facts(cube: str) -> dict:
    """Everything code can establish about one cube, for the meaning layer and its checks."""
    import data_layer
    schema = parse_schema(cubes.schema_file(cube).read_text(encoding="utf-8"))
    profile = data_layer.profile(cube) or {}
    main_date = profile.get("default_date") or next(
        (c["column"] for c in schema["columns"] if c["type"].startswith("Date")), "")
    names = [m["name"] for m in schema["measures"]]
    activity = measure_activity(cube, names, main_date) if main_date and names else {}
    main_measure = next((m["name"] for m in profile.get("measures", []) if m.get("aggregation") == "additive"),
                        names[0] if names else "")
    dates = [c for c in schema["columns"] if c["type"].startswith("Date")]
    coverage = {c["column"]: date_coverage(cube, c["column"], main_measure) for c in dates} if main_measure else {}
    for m in schema["measures"]:
        m["activity"] = activity.get(m["name"], {})
    return {"cube": cube, "read": date.today().isoformat(), "main_date": main_date, "main_measure": main_measure,
            "measures": schema["measures"], "columns": schema["columns"], "date_coverage": coverage}


def write_facts(cube_names: list[str] | None = None, missing_only: bool = False) -> None:
    import data_layer
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    for cube in cube_names or data_layer.layer_cubes():
        if missing_only and (FACTS_DIR / f"{cubes.slug(cube)}.json").exists():
            continue
        facts = build_facts(cube)
        (FACTS_DIR / f"{cubes.slug(cube)}.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False),
                                                            encoding="utf-8")
        live = sum(1 for m in facts["measures"] if m["activity"].get("all_time"))
        recent = sum(1 for m in facts["measures"] if m["activity"].get("last_12_months"))
        cov = facts["date_coverage"].get(facts["main_date"], {})
        print(f"{cube[21:]:45} measures {len(facts['measures']):3} (data {live}, recent {recent})  "
              f"main date {cov.get('first')} -> {cov.get('last')}  dates {len(facts['date_coverage'])}", flush=True)


# ---------------------------------------------------------------- checking the meaning files --

AGGREGATIONS = {"sum", "average", "ratio", "distinct_count", "max", "min", "last"}


def cube_files() -> dict[str, dict]:
    """{cube: its meaning file}, as shipped (semantic/cubes/*.json)."""
    out = {}
    for path in sorted((SEMANTIC_DIR / "cubes").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["cube"]] = data
    return out


def check_cube(data: dict, facts: dict) -> list[str]:
    """Everything in one cube's meaning file that disagrees with the cube itself (empty = all good)."""
    problems = []
    schema_measures = {m["name"]: m for m in facts["measures"]}
    columns = {c["column"]: c for c in facts["columns"]}
    names = [m["name"] for m in data["measures"]]
    for name in set(schema_measures) - set(names):
        problems.append(f"measure {name} is missing")
    for name in {n for n in names if names.count(n) > 1}:
        problems.append(f"measure {name} is listed more than once")
    roles = {d["role"] for d in data["dates"]}
    defaults = [d for d in data["dates"] if d.get("default")]
    if len(defaults) != 1:
        problems.append(f"{len(defaults)} default dates (need exactly one)")
    for d in data["dates"]:
        col = columns.get(d["column"])
        if col is None or not col["type"].startswith("Date"):
            problems.append(f"date {d['column']} is not a date column of the cube")
        if d.get("default") and d["role"] == "last_year_date":
            problems.append("the default date is a last-year helper")
    for m in data["measures"]:
        name, fact = m["name"], schema_measures.get(m["name"], {})
        activity = fact.get("activity", {})
        if name not in schema_measures:
            problems.append(f"measure {name} is not in the cube")
        if m["status"] not in ("active", "hidden"):
            problems.append(f"measure {name}: status {m['status']!r}")
        if m["status"] == "hidden":
            if not m.get("hidden_reason"):
                problems.append(f"measure {name} is hidden without a reason")
            continue
        if m["aggregation"] not in AGGREGATIONS:
            problems.append(f"measure {name}: aggregation {m['aggregation']!r}")
        if any(k.endswith("_error") for k in activity):
            problems.append(f"measure {name} is active but broken on the server")
        if activity and activity.get("all_time") is None and activity.get("last_12_months") is None:
            problems.append(f"measure {name} is active but has no data")
        if m.get("default_date_role") and m["default_date_role"] not in roles:
            problems.append(f"measure {name}: default date role {m['default_date_role']!r} is not a date of the cube")
        if any(r not in roles for r in m.get("date_roles", [])):
            problems.append(f"measure {name}: unknown date roles {m['date_roles']}")
    for b in data["breakdowns"]:
        col = columns.get(b["column"])
        if col is None:
            problems.append(f"breakdown {b['column']} is not in the cube")
            continue
        if sorted(b.get("needs_columns", [])) != sorted(col["group_with"]):
            problems.append(f"breakdown {b['column']}: needs_columns {b.get('needs_columns')} but the cube says "
                            f"{col['group_with']}")
        listed = {v["value"] for v in col["values"]}
        if b.get("sample_values") and b.get("kind") != "enum":
            problems.append(f"breakdown {b['column']}: sample values on a {b.get('kind')} breakdown")
        if listed and any(v not in listed for v in b.get("sample_values", [])):
            problems.append(f"breakdown {b['column']}: sample values not stored in the cube")
    for f in data["named_filters"]:
        col = columns.get(f["column"])
        if col is None:
            problems.append(f"named filter {f['name']!r}: column {f['column']} is not in the cube")
            continue
        listed = {v["value"] for v in col["values"]}
        missing = [v for v in f.get("values", []) if listed and v not in listed]
        if missing:
            problems.append(f"named filter {f['name']!r}: values not stored in the cube: {missing}")
    main = data["coverage"].get("main_date")
    if main != (defaults[0]["column"] if defaults else None):
        problems.append(f"coverage.main_date {main} is not the default date")
    return problems


def term_owners(files: dict[str, dict]) -> dict[str, list[tuple[str, str]]]:
    """{business term: [(cube, measure), ...]} over the active measures of every cube."""
    owners: dict[str, list[tuple[str, str]]] = {}
    for cube, data in files.items():
        for m in data["measures"]:
            if m["status"] == "active":
                for term in m.get("terms", []):
                    owners.setdefault(term.strip().lower(), []).append((cube, m["name"]))
    return owners


def check_all() -> tuple[dict[str, list[str]], dict[str, list[tuple[str, str]]]]:
    """(problems per cube, terms claimed by more than one measure)."""
    files = cube_files()
    problems = {}
    for cube, data in files.items():
        facts_path = FACTS_DIR / f"{cubes.slug(cube)}.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else None
        problems[cube] = check_cube(data, facts) if facts else ["no facts read for this cube"]
    conflicts = {t: o for t, o in term_owners(files).items() if len(o) > 1}
    return problems, conflicts


# ---------------------------------------------------------------- using it --

_cache: dict = {"key": None}


def overrides_file() -> Path:
    return config.DATA_DIR / "semantic_overrides.json"


def _sources() -> list[Path]:
    return sorted((SEMANTIC_DIR / "cubes").glob("*.json")) + [SEMANTIC_DIR / "terms.json", SEMANTIC_DIR / "review.json",
                                                             overrides_file()]


def _state() -> dict:
    """The meaning files and admins' decisions, read again whenever one of them changes."""
    key = tuple((str(p), p.stat().st_mtime) for p in _sources() if p.exists())
    if _cache["key"] != key:
        read = lambda p, empty: json.loads(p.read_text(encoding="utf-8")) if p.exists() else empty
        decided = read(overrides_file(), {}).get("decisions", {})
        review = [{**r, **({"answer": decided[r["id"]]["answer"], "status": "agreed"} if r["id"] in decided else {})}
                  for r in read(SEMANTIC_DIR / "review.json", {"items": []})["items"]]
        _cache.update(key=key, files=cube_files() if (SEMANTIC_DIR / "cubes").exists() else {},
                      terms=read(SEMANTIC_DIR / "terms.json", {"terms": {}})["terms"], review=review, needs={})
    return _cache


def cube(name: str) -> dict | None:
    return _state()["files"].get(name)


def usable(name: str) -> bool:
    """False for a cube the meaning layer says has no data (it should never be picked for a question)."""
    data = cube(name)
    return data is None or (bool(data["coverage"].get("first")) and
                            any(m["status"] == "active" for m in data["measures"]))


def hidden(name: str) -> dict[str, str]:
    """{measure: why} for the measures a query must not use."""
    data = cube(name) or {"measures": []}
    return {m["name"]: m.get("hidden_reason", "") for m in data["measures"] if m["status"] == "hidden"}


def card(name: str) -> str | None:
    """A cube's index card from the meaning layer: what it is for, where its data is, its main measures."""
    data = cube(name)
    if data is None:
        return None
    head = f"### {data['label']} - cube \"{name}\""
    if not usable(name):
        return f"{head}\nNO DATA in this cube: never use it. {data['coverage'].get('note', '')}".rstrip()
    cov = data["coverage"]
    default = next((d for d in data["dates"] if d.get("default")), {})
    active = [m["label"] for m in data["measures"] if m["status"] == "active"]
    lines = [head, data["purpose"], f"Grain: {data['grain']}",
             f"Data: {cov.get('first')} to {cov.get('last')} by {default.get('label', cov.get('main_date'))}"
             + (f". {cov['note']}" if cov.get("note") else ""),
             "Use for: " + "; ".join(data.get("use_for", [])[:6])]
    if data.get("not_for"):
        lines.append("Not for: " + "; ".join(data["not_for"][:4]))
    lines.append("Measures: " + ", ".join(dict.fromkeys(active))[:600])
    entities = dict.fromkeys(b["entity"] for b in data["breakdowns"]
                             if b.get("status", "active") == "active" and b.get("entity") not in (None, "", "other"))
    if entities:
        lines.append("By: " + ", ".join(entities))
    return "\n".join(lines)


def decisions(name: str | None = None) -> list[dict]:
    """The decisions only a person can make (one cube's, or all), each "proposed" or "agreed"."""
    return [r for r in _state()["review"] if name is None or r["cube"] == name]


def drift() -> list[str]:
    """Cubes whose structure changed on the server since the meaning layer was built (it needs a review for
    them): the data layer's fingerprint of each cube against the one in semantic/manifest.json."""
    import data_layer
    path = SEMANTIC_DIR / "manifest.json"
    if not path.exists():
        return []
    built = json.loads(path.read_text(encoding="utf-8")).get("cubes", {})
    profiles = data_layer.load().get("cubes", {})
    return [c for c, info in built.items()
            if info.get("fingerprint") and profiles.get(c, {}).get("fingerprint") not in (None, "", info["fingerprint"])]


def save_decision(item_id: str, answer: str, by: str = "admin") -> None:
    """An admin's answer to a decision; it wins over the proposed answer and survives updates."""
    from datetime import datetime
    path = overrides_file()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("decisions", {})[item_id] = {"answer": answer, "by": by,
                                                "time": datetime.now().isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def details_text(name: str) -> str:
    """The meaning layer of one cube, for writing its queries (it wins over anything else Claude reads)."""
    data = cube(name)
    if data is None:
        return ""
    lines = ["## Meaning layer (authoritative: follow it over the structure above)", data["purpose"],
             f"Grain: {data['grain']}"]
    cov = data["coverage"]
    lines.append(f"Data: {cov.get('first')} to {cov.get('last')}" + (f". {cov['note']}" if cov.get("note") else ""))
    lines += ["", "### Dates (filter the period on the default unless the question names another)"]
    for d in data["dates"]:
        if d["role"] == "last_year_date":
            continue
        lines.append(f"- {d['column']}: {d['label']}{' (DEFAULT)' if d.get('default') else ''} - {d['meaning']} "
                     f"Words: {', '.join(d.get('words', [])[:6])}. Data {d.get('first')} to {d.get('last')}.")
    lines += ["", "### Measures (use only these; name the one you use)"]
    for m in data["measures"]:
        if m["status"] != "active":
            continue
        unit = m["unit"] + ("" if m["aggregation"] == "sum" else f", {m['aggregation']} - never add it up")
        lines.append(f"- {m['name']} = {m['label']}: {m['definition']} ({unit}; date: {m.get('default_date_role')}). "
                     f"Terms: {', '.join(m.get('terms', [])[:6])}." + (f" {m['notes']}" if m.get("notes") else ""))
    off = hidden(name)
    if off:
        lines += ["", "### Never use these measures (helpers, duplicates, broken or empty): " + ", ".join(off)]
    lines += ["", "### Breakdowns (always group with the helper columns listed)"]
    for b in data["breakdowns"]:
        if b.get("status", "active") != "active":
            continue
        extra = f" + {', '.join(b['needs_columns'])}" if b.get("needs_columns") else ""
        values = f" Values: {', '.join(b['sample_values'][:8])}." if b.get("sample_values") else ""
        lines.append(f"- {b['column']}{extra}: {b['label']} ({b.get('kind', '')}). {b.get('meaning', '')}{values}")
    if data.get("named_filters"):
        lines += ["", "### Named filters (use these exact values)"]
        lines += [f"- {f['name']}: {f['column']} in {json.dumps(f['values'], ensure_ascii=False)} - {f['meaning']}"
                  for f in data["named_filters"]]
    if data.get("rules"):
        lines += ["", "### Rules"] + [f"- {r}" for r in data["rules"]]
    made = decisions(name)
    if made:
        lines += ["", "### Decisions (agreed ones are final; proposed ones are the default until a person decides)"]
        lines += [f"- ({r['status']}) {r['question']} -> {r.get('answer', r['proposed'])}" for r in made]
    return "\n".join(lines)


def term_hits(question: str) -> list[dict]:
    """Business terms of the meaning layer found in the question, longest first:
    [{kind: "term", text, cube, measure, label, filter}] - the measure each one means."""
    words = re.findall(r"[^\W_][\w&'%.-]*", question.lower())
    terms, found, used = _state()["terms"], [], set()
    for n in (5, 4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            span = range(i, i + n)
            phrase = " ".join(words[i:i + n])
            if phrase in terms and not used.intersection(span):
                used.update(span)
                found.append({"kind": "term", "text": phrase, **terms[phrase]})
    return found


def hits_text(hits: list[dict]) -> str:
    return "\n".join(f'- "{h["text"]}" means {h["label"]}: measure {h["measure"]} of cube "{h["cube"]}"'
                     + (f' with the named filter "{h["filter"]}"' if h.get("filter") else "") for h in hits)


def needed_columns(name: str) -> dict[str, list[str]]:
    """{column: helper columns the cube requires next to it}, from the cube's structure file."""
    needs = _state()["needs"]
    if name not in needs:
        path = cubes.schema_file(name)
        needs[name] = ({c["column"]: c["group_with"] for c in parse_schema(path.read_text(encoding="utf-8"))["columns"]
                        if c["group_with"]} if path.exists() else {})
    return needs[name]


_COL = r"'(?:[^']|'')+'\[[^\]]+\]"


def add_needed_columns(query: str, needs: dict[str, list[str]]) -> str:
    """The query with every column grouped by a SUMMARIZECOLUMNS followed by the helper columns the cube
    requires (composite keys), which a query must list or the server rejects it."""
    out, pos = [], 0
    for m in re.finditer(r"SUMMARIZECOLUMNS\s*\(", query, flags=re.IGNORECASE):
        start = m.end()
        stop = re.search(r'"|KEEPFILTERS|\bFILTER\s*\(|TREATAS|CALCULATETABLE|\bALL\s*\(|\bVALUES\s*\(',
                         query[start:], flags=re.IGNORECASE)
        segment = query[start:start + (stop.start() if stop else len(query) - start)]
        grouped = list(re.finditer(_COL, segment))
        missing = [h for g in grouped for h in needs.get(g.group(0), []) if h not in query]
        if grouped and missing:
            at = start + grouped[-1].end()
            out += [query[pos:at], ", " + ", ".join(dict.fromkeys(missing))]
            pos = at
    return _filters_with_helpers("".join(out) + query[pos:], needs)


_ALL_LIKE = re.compile(r"\b(ALL|ALLSELECTED|ALLNOBLANKROW|REMOVEFILTERS)\s*\(", re.IGNORECASE)


def _filters_with_helpers(query: str, needs: dict[str, list[str]]) -> str:
    """Filters on a composite-key column need its helper columns too: ALL('T'[C]) becomes
    ALL('T'[C], 'T'[C.UniqueName]), and TREATAS({...}, 'T'[C]) becomes
    FILTER(ALL('T'[C], 'T'[C.UniqueName]), 'T'[C] IN {...}) (the same filter, which the server accepts)."""
    def treatas(m):
        column = m.group(2)
        helpers = needs.get(column)
        if not helpers:
            return m.group(0)
        return f"FILTER(ALL({column}, {', '.join(helpers)}), {column} IN {m.group(1)})"
    query = re.sub(r"TREATAS\s*\(\s*(\{[^{}]*\})\s*,\s*(" + _COL + r")\s*\)", treatas, query, flags=re.IGNORECASE)
    out, pos = [], 0
    for m in _ALL_LIKE.finditer(query):
        depth, end = 1, m.end()
        while end < len(query) and depth:
            depth += {"(": 1, ")": -1}.get(query[end], 0)
            end += 1
        inner = query[m.end():end - 1]
        args = [a.strip() for a in inner.split(",")]
        if not all(re.fullmatch(_COL, a) for a in args):  # ALL('Table') or anything but plain columns: as it is
            continue
        missing = [h for a in args for h in needs.get(a, []) if h not in args]
        if missing:
            out += [query[pos:end - 1], ", " + ", ".join(dict.fromkeys(missing))]
            pos = end - 1
    return "".join(out) + query[pos:]


def compact_structure(schema_text: str, meaning: str) -> str:
    """The cube's structure cut to what its meaning layer refers to: the columns it names (with their helper
    columns and values), not the measures it hides or the dozens of date attributes no question needs. A
    third of the size; get_cube_details still gives everything."""
    keep = []
    for line in schema_text.splitlines():
        if line.startswith("# Model"):
            keep.append(line)
        elif m := re.match(r"- (" + _COL + r") \(", line):
            if m.group(1) in meaning:
                keep.append(line if len(line) <= 400 else line[:400] + " ...")
    return (keep[0] + "\n" if keep and keep[0].startswith("# Model") else "") + (
        "## Columns the meaning layer names (exact names, helper columns and values; get_cube_details gives "
        "every column and measure of the cube)\n" + "\n".join(k for k in keep if not k.startswith("# Model")))


def composite_key_hint(cube: str, error: str) -> str:
    """For the server's 'Column [X] is part of composite key' error: which helper columns go with X, and
    how to filter it, so Claude's retry fixes it."""
    m = re.search(r"Column \[([^\]]+)\] is part of composite key", error)
    if not m:
        return ""
    columns = {c: h for c, h in needed_columns(cube).items() if c.endswith(f"[{m.group(1)}]")}
    if not columns:
        return ""
    column, helpers = next(iter(columns.items()))
    return (f" {column} must always be used together with {', '.join(helpers)}: group by both, list both in ALL(), "
            f"and filter it as KEEPFILTERS(FILTER(ALL({column}, {', '.join(helpers)}), {column} = <value>)), never with "
            f"TREATAS or {column} = <value> as a CALCULATE filter.")


# ---------------------------------------------------------------- the shared files --

VERSION = "1.0.0"
# Business words no cube claims on its own: what they mean across the cubes (or that they must be asked).
EXTRA_TERMS = {
    "cancellations": {"cube": "GlobalTravelEngine - Bookings", "measure": "[Reservations Count]",
                      "filter": "cancelled bookings"},
    "cancelled bookings": {"cube": "GlobalTravelEngine - Bookings", "measure": "[Reservations Count]",
                           "filter": "cancelled bookings"},
}
AMBIGUOUS_TERMS = {
    "errors": ["Statistics Zone [Requests KO] - failed client searches",
               "Statistics Supplier Error API Hotel [Requests] with the supplier api errors filter - errors from suppliers"],
}


def build_shared() -> dict:
    """Write terms.json, review.json and manifest.json from the cube files."""
    import data_layer
    files = cube_files()
    clashes = {t: o for t, o in term_owners(files).items() if len(o) > 1}
    if clashes:
        raise ValueError(f"terms claimed twice: {sorted(clashes)}")
    labels = {(c, m["name"]): m["label"] for c, d in files.items() for m in d["measures"]}
    terms = {t: {"cube": o[0][0], "measure": o[0][1], "label": labels[o[0]]}
             for t, o in sorted(term_owners(files).items())}
    terms.update({t: {**v, "label": labels[(v["cube"], v["measure"])]} for t, v in EXTRA_TERMS.items()})
    review = [{"cube": c, **r, "status": "proposed"} for c, d in files.items() for r in d["review"]]
    layer = data_layer.load().get("cubes", {})
    manifest = {"version": VERSION, "built": date.today().isoformat(),
                "cubes": {c: {"label": d["label"], "fingerprint": layer.get(c, {}).get("fingerprint", ""),
                              "active_measures": sum(m["status"] == "active" for m in d["measures"]),
                              "hidden_measures": sum(m["status"] == "hidden" for m in d["measures"]),
                              "coverage": d["coverage"]} for c, d in files.items()}}
    for name, data in (("terms", {"version": VERSION, "terms": terms, "ambiguous": AMBIGUOUS_TERMS}),
                       ("review", {"version": VERSION, "items": review}), ("manifest", manifest)):
        (SEMANTIC_DIR / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"terms": len(terms), "review": len(review), "cubes": len(files)}


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    if sys.argv[1:2] == ["build"]:
        print(build_shared())
        sys.exit(0)
    if sys.argv[1:2] == ["check"]:
        found, clashes = check_all()
        for cube, items in found.items():
            print(f"{cube[21:]}: {'ok' if not items else f'{len(items)} problem(s)'}")
            for item in items:
                print(f"   - {item}")
        print(f"\n{len(clashes)} terms claimed by more than one measure:")
        for term, owners in sorted(clashes.items()):
            print(f"   {term!r}: " + "; ".join(f"{c[21:]} {m}" for c, m in owners))
        sys.exit(0)
    if sys.argv[1:2] == ["facts"]:
        names = [a for a in sys.argv[2:] if a != "--missing"]
        write_facts(names or None, missing_only="--missing" in sys.argv)
    else:
        print(__doc__)
