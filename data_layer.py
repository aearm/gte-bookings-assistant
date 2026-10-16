"""The data layer: one model of all connected cubes that Claude reads before it writes any query.

Built once after installation (Cubes page › Build the data layer, or `python build_layer.py`),
then everything Chat and the dashboards know about the data comes from it. Rebuild after cubes
change; only the cubes that changed are profiled again.

It follows the usual layering of a semantic model:
1. Physical layer - per cube, its exact structure and every value with how much data it has
   (models/<cube>/schema.md and value_index.json). Queries are written against these names.
2. Semantic layer - models/data_layer/layer.json. Per cube: what it is for, its grain (what one
   row is), its measures with business names, synonyms, units and whether they add up, what each
   date means, and which business entity each dimension describes (customer, supplier, hotel...).
   Across cubes: the conformed (shared) dimensions - the same customer, supplier or hotel in
   several cubes - with the join column in each cube and how well their values really match
   (measured on the data, not guessed from names): a bus matrix. Plus which cube to use for what.
3. Catalog - models/data_layer/catalog.md: the semantic layer written for Claude and given with
   every question. When Claude needs a cube's exact names and values it reads its physical layer.

A query on one cube is DAX (SQL on local files). A question that needs several cubes becomes one
query per cube, joined on the shared dimensions (see plans.py)."""
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import config
import cubes
import glossary
import llm
import usage
import value_index
from backends import get_backend

VERSION = 1
LAYER_DIR = config.MODELS_DIR / "data_layer"
LAYER_FILE = LAYER_DIR / "layer.json"
CATALOG_FILE = LAYER_DIR / "catalog.md"

ENTITIES = ["date", "booking", "customer", "supplier", "hotel", "product", "destination", "country", "market",
            "sale_channel", "status", "currency", "payment", "user", "api_interface", "request_type",
            "room_or_rate", "transfer", "ticket", "department", "other"]
UNITS = ["count", "currency", "percent", "ratio", "duration", "bytes", "number"]
AGGREGATIONS = ["additive", "semi_additive", "non_additive"]
MIN_VALUES_FOR_MATCH = 5      # columns with fewer distinct values (Yes/No...) say nothing about joins
COMMON_VALUE_LIMIT = 40       # a value found in more columns than this ("UNKNOWN") is ignored
_IGNORED_VALUES = {"", "UNKNOWN", "N/A", "NA", "NONE", "NULL", "-", "(BLANK)", "OTHERS", "OTHER", "ALL"}


# ---------------------------------------------------------------- reading the physical layer --

def schema_names(schema_text: str) -> dict:
    """Measures, columns (with type) and tables named in a cube's schema.md."""
    measures = set(re.findall(r"^- (\[[^\]]+\])", schema_text, flags=re.MULTILINE))
    columns = {}
    for m in re.finditer(r"^- ('(?:[^']|'')+'\[[^\]]+\]|\"[^\"]+\") \(([^)]*)\)", schema_text, flags=re.MULTILINE):
        columns[m.group(1)] = m.group(2)
    tables = {re.match(r"'((?:[^']|'')+)'", c).group(1) for c in columns if c.startswith("'")}
    tables |= set(re.findall(r'^## Table "([^"]+)"', schema_text, flags=re.MULTILINE))
    return {"measures": measures, "columns": columns, "tables": tables}


def fingerprint(schema_text: str) -> str:
    """Changes when measures or columns change, not when the data (values, counts) does."""
    names = schema_names(schema_text)
    parts = sorted(names["measures"]) + sorted(f"{c} {t}" for c, t in names["columns"].items())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def date_columns(schema_text: str) -> list[str]:
    return [c for c, t in schema_names(schema_text)["columns"].items()
            if t.startswith("Date") or t.split()[0].upper() in ("DATE", "TIMESTAMP")]


# ---------------------------------------------------------------- 2a. profile one cube --

_DIMENSION = {
    "type": "object",
    "properties": {
        "table": {"type": "string", "description": "Exact table (dimension) name."},
        "entity": {"type": "string", "enum": ENTITIES},
        "meaning": {"type": "string", "description": "What it describes, in plain words."},
        "key_column": {"type": "string", "description": "Exact column that identifies a member best for joining "
                                                         "with other cubes: a code/ID if there is one, else the name. Empty if none."},
        "name_column": {"type": "string", "description": "Exact column with the readable name, or empty."},
    },
    "required": ["table", "entity", "meaning", "key_column", "name_column"],
    "additionalProperties": False,
}
PROFILE_TOOL = {
    "name": "submit_profile",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "Short business name of the cube, e.g. Bookings, Booking payments."},
            "subject_area": {"type": "string", "description": "e.g. Sales, Payments, Hotel inventory, API traffic, Supplier performance."},
            "description": {"type": "string", "description": "2-3 plain sentences: what the cube contains and who uses it."},
            "grain": {"type": "string", "description": "What one fact row is, e.g. one booking line; one API request summary per hour."},
            "use_for": {"type": "array", "items": {"type": "string"}, "description": "3-8 kinds of questions this cube answers."},
            "not_for": {"type": "array", "items": {"type": "string"}, "description": "Common confusions or limits, or empty."},
            "default_date": {"type": "string", "description": "Exact date column most questions about 'March' or 'this year' mean."},
            "dates": {"type": "array", "items": {
                "type": "object",
                "properties": {"column": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["column", "meaning"], "additionalProperties": False}},
            "measures": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact measure, e.g. [Final Sales] (SQL: an aggregate expression)."},
                    "label": {"type": "string", "description": "Business name, e.g. Sales."},
                    "synonyms": {"type": "array", "items": {"type": "string"}},
                    "meaning": {"type": "string"},
                    "unit": {"type": "string", "enum": UNITS},
                    "aggregation": {"type": "string", "enum": AGGREGATIONS, "description": (
                        "additive: can be summed over every breakdown (sales, counts); semi_additive: not over "
                        "time (balances, stock, allotment); non_additive: averages, percentages, ratios, distinct counts.")},
                },
                "required": ["name", "label", "synonyms", "meaning", "unit", "aggregation"],
                "additionalProperties": False}},
            "variants": {"type": "string", "description": "How variant measures are named (e.g. 'LY' = same period last "
                                                          "year, 'LYS' = last year same weekday, 'Var LY' = % change), or empty."},
            "dimensions": {"type": "array", "items": _DIMENSION},
            "filters": {"type": "array", "items": {
                "type": "object",
                "properties": {"meaning": {"type": "string"}, "filter": {"type": "string", "description": "Exact filter."}},
                "required": ["meaning", "filter"], "additionalProperties": False},
                "description": "Groups people will mean, e.g. valid / confirmed / cancelled bookings, with exact values."},
            "example_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["label", "subject_area", "description", "grain", "use_for", "not_for", "default_date", "dates",
                     "measures", "variants", "dimensions", "filters", "example_questions"],
    },
}

PROFILE_RULES = """You are building the semantic layer of a travel company's data platform: a catalog
that lets an assistant pick the right cube and write correct queries for business questions.
Describe ONE cube from its schema below (measures, columns, and each column's real values with how
much data each has).

- Use only names that appear in the schema, written exactly (measures as [Name], columns as 'Table'[Column];
  for SQL data, columns as "Column" and measures as aggregate expressions such as SUM("Sales USD")).
- measures: every measure that is NOT a variant of another one (skip the LY / LYS / Var / Opt / Growth
  versions and describe their naming once in `variants`). Give each a business label people would use,
  synonyms (including other languages used in the names), unit and aggregation.
- dates: every date column with what it means (booking made, travel, payment, request...). Pick the
  default date most questions mean.
- dimensions: every table people group or filter by, with the business entity it describes and its best
  join key (a code or ID when there is one).
- filters: groups people will mean (valid, confirmed, cancelled, errors...) using exact values with data.
- 4-6 example questions in plain English that this cube answers well.
Be precise and brief: this text is read before every question."""


def profile_cube(cube: str, schema_text: str, language: str) -> dict:
    """Claude's description of one cube (checked against its schema)."""
    notes = glossary.notes_for_claude(cube)
    user = f"Cube: {cube}\nQuery language: {language}\n\n{schema_text}"
    if notes.strip():
        user += "\n\n## Notes and agreed meanings from the business\n" + notes
    profile = llm._structured_call([{"type": "text", "text": PROFILE_RULES}], PROFILE_TOOL, user, purpose="profile",
                                   model=config.CLAUDE_LAYER_MODEL, effort="high", max_tokens=48000)
    return _clean_profile(profile, schema_text, language)


def _clean_profile(p: dict, schema_text: str, language: str) -> dict:
    """Keep only names that exist in the cube, so the layer can't send Claude to a made-up column."""
    names = schema_names(schema_text)
    cols, warnings = names["columns"], []

    def col(ref: str) -> str:
        ref = (ref or "").strip()
        if not ref or ref in cols:
            return ref
        warnings.append(f"unknown column {ref}")
        return ""

    if language == "DAX":
        kept = [m for m in p.get("measures", []) if m.get("name") in names["measures"]]
        warnings += [f"unknown measure {m.get('name')}" for m in p.get("measures", []) if m not in kept]
        p["measures"] = kept
    p["default_date"] = col(p.get("default_date", ""))
    p["dates"] = [d for d in p.get("dates", []) if col(d.get("column", ""))]
    if not p["default_date"] and p["dates"]:
        p["default_date"] = p["dates"][0]["column"]
    dims = []
    for d in p.get("dimensions", []):
        d["key_column"], d["name_column"] = col(d.get("key_column", "")), col(d.get("name_column", ""))
        if d.get("entity") not in ENTITIES:
            d["entity"] = "other"
        if d.get("key_column") or d.get("name_column") or d.get("table") in names["tables"]:
            dims.append(d)
    p["dimensions"] = dims
    p["warnings"] = warnings
    return p


# ---------------------------------------------------------------- 2b. shared dimensions --

def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().upper()


def _value_sets(cube_names: list[str]) -> dict[tuple[str, str], set]:
    """(cube, column) -> its normalized values, for every indexed text column (in memory or on disk)."""
    sets = {}
    for cube in cube_names:
        for column, values in value_index.for_cube(cube).all_values():
            vals = {_norm(v) for v in values} - _IGNORED_VALUES
            if len(vals) >= MIN_VALUES_FOR_MATCH:
                sets[(cube, column)] = vals
    return sets


def _match(a: set | None, b: set | None) -> dict | None:
    """How well two columns' values match: share of the smaller one found in the other."""
    if not a or not b:
        return None
    shared = len(a & b)
    return {"shared": shared, "of_smaller": round(shared / min(len(a), len(b)), 3),
            "sizes": [len(a), len(b)]}


def entity_members(profiles: dict[str, dict], sets: dict) -> dict[str, list[dict]]:
    """entity -> [{cube, table, key_column, name_column, match (vs the entity's largest member)}]."""
    groups: dict[str, list[dict]] = {}
    for cube, p in profiles.items():
        for d in p.get("dimensions", []):
            if d["entity"] in ("date", "other", "status"):
                continue
            groups.setdefault(d["entity"], []).append(
                {"cube": cube, "table": d.get("table", ""), "key_column": d.get("key_column", ""),
                 "name_column": d.get("name_column", "")})
    for entity, members in groups.items():
        def size(m, col):
            return len(sets.get((m["cube"], m[col]), ()))
        hub = max(members, key=lambda m: (size(m, "key_column"), size(m, "name_column")))
        for m in members:
            if m is hub:
                m["hub"] = True
                continue
            m["key_match"] = _match(sets.get((m["cube"], m["key_column"])), sets.get((hub["cube"], hub["key_column"])))
            m["name_match"] = _match(sets.get((m["cube"], m["name_column"])), sets.get((hub["cube"], hub["name_column"])))
    return {e: ms for e, ms in groups.items() if len({m["cube"] for m in ms}) > 1}


def column_links(sets: dict, already: set[tuple[str, str]], limit: int = 40) -> list[dict]:
    """Columns in different cubes whose values largely match, found from the values themselves
    (an inverted index of every value). Catches shared dimensions the profiles named differently."""
    where: dict[str, list[tuple[str, str]]] = {}
    for key, vals in sets.items():
        for v in vals:
            where.setdefault(v, []).append(key)
    shared: dict[tuple, int] = {}
    for v, keys in where.items():
        if len(keys) > COMMON_VALUE_LIMIT:
            continue
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if a[0] != b[0]:
                    pair = (a, b) if a < b else (b, a)
                    shared[pair] = shared.get(pair, 0) + 1
    links = []
    for (a, b), n in shared.items():
        if n < MIN_VALUES_FOR_MATCH or a in already and b in already:
            continue
        ratio = n / min(len(sets[a]), len(sets[b]))
        if ratio >= 0.6:
            links.append({"a": {"cube": a[0], "column": a[1]}, "b": {"cube": b[0], "column": b[1]},
                          "shared": n, "of_smaller": round(ratio, 3)})
    links.sort(key=lambda x: (-x["shared"], -x["of_smaller"]))
    return links[:limit]


_MEMBER = {
    "type": "object",
    "properties": {
        "cube": {"type": "string"},
        "join_column": {"type": "string", "description": "Exact column to join on in this cube."},
        "display_column": {"type": "string", "description": "Exact column with the readable name, or empty."},
        "match": {"type": "string", "enum": ["high", "partial", "names_only", "unknown"]},
    },
    "required": ["cube", "join_column", "display_column", "match"],
    "additionalProperties": False,
}
CONFORM_TOOL = {
    "name": "submit_shared_dimensions",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"}, "label": {"type": "string"}, "description": {"type": "string"},
                    "members": {"type": "array", "items": _MEMBER},
                    "join_notes": {"type": "string", "description": "How to join safely (e.g. compare upper(trim(name)); "
                                                                    "codes are numbers in one cube and text in another)."},
                },
                "required": ["entity", "label", "description", "members", "join_notes"],
                "additionalProperties": False}},
            "routing": {"type": "array", "items": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "cube": {"type": "string"}, "why": {"type": "string"}},
                "required": ["topic", "cube", "why"], "additionalProperties": False},
                "description": "Which cube to use for each common topic, especially where several cubes could answer."},
            "cross_cube_questions": {"type": "array", "items": {"type": "string"},
                                     "description": "4-8 useful questions that need two cubes joined."},
        },
        "required": ["entities", "routing", "cross_cube_questions"],
    },
}

CONFORM_RULES = """You are designing the conformed dimensions (the bus matrix) of a travel company's
data platform. Each cube below is a separate Analysis Services database, so numbers from two cubes can
only be combined by querying each cube and joining the results on a shared dimension.

From the cube profiles and the measured value matches, decide:
- entities: each business entity found in several cubes (customer, supplier, hotel, country...), with its
  member cubes and, per cube, the exact column to join on. Prefer codes/IDs where the values match;
  use names only when a cube has no matching code (match = names_only). Leave out cubes whose values
  don't match (a different meaning of the same word). Explain in join_notes how to join safely.
- routing: for each common topic (sales and profit, bookings count, payments, allotment, API traffic,
  errors, prices...) which cube is the source to use, and why - especially where several cubes overlap.
- cross_cube_questions: useful questions that need two cubes joined.
Use only cube and column names given below, written exactly."""


def conform(profiles: dict[str, dict], members: dict, links: list[dict]) -> dict:
    """Claude names the shared dimensions and picks each cube's join column, from measured matches."""
    if len(profiles) < 2:
        return {"entities": [], "routing": [], "cross_cube_questions": []}
    lines = ["## Cube profiles"]
    for cube, p in profiles.items():
        lines.append(f"### {cube} ({p.get('label', '')}) - {p.get('description', '')} Grain: {p.get('grain', '')}")
        lines.append("Measures: " + ", ".join(f"{m['label']} {m['name']}" for m in p.get("measures", [])[:40]))
        for d in p.get("dimensions", []):
            lines.append(f"- {d['entity']}: table '{d['table']}' key {d['key_column'] or '-'} name {d['name_column'] or '-'}")
    lines.append("\n## Measured value matches per entity (share of the smaller column's values found in the "
                 "largest member, the 'hub')")
    for entity, ms in members.items():
        lines.append(f"### {entity}")
        for m in ms:
            if m.get("hub"):
                lines.append(f"- HUB {m['cube']}: key {m['key_column'] or '-'}, name {m['name_column'] or '-'}")
            else:
                fmt = lambda x: f"{x['of_smaller']:.0%} of {min(x['sizes']):,}" if x else "not measured"
                lines.append(f"- {m['cube']}: key {m['key_column'] or '-'} ({fmt(m.get('key_match'))}), "
                             f"name {m['name_column'] or '-'} ({fmt(m.get('name_match'))})")
    if links:
        lines.append("\n## Other columns whose values largely match across cubes")
        for x in links:
            lines.append(f"- {x['a']['cube']} {x['a']['column']} ~ {x['b']['cube']} {x['b']['column']}: "
                         f"{x['shared']:,} shared values ({x['of_smaller']:.0%})")
    result = llm._structured_call([{"type": "text", "text": CONFORM_RULES}], CONFORM_TOOL, "\n".join(lines), purpose="conform",
                                  model=config.CLAUDE_LAYER_MODEL, effort="high", max_tokens=48000)
    return _clean_conform(result, profiles)


def _clean_conform(result: dict, profiles: dict[str, dict]) -> dict:
    """Drop members whose cube or join column doesn't exist."""
    columns = {c: schema_names(cubes.schema_file(c).read_text(encoding="utf-8"))["columns"]
               for c in profiles if cubes.schema_file(c).exists()}
    entities = []
    for e in result.get("entities", []):
        kept = []
        for m in e.get("members", []):
            cols = columns.get(m["cube"], {})
            if m["join_column"] in cols:
                m["display_column"] = m["display_column"] if m.get("display_column") in cols else ""
                kept.append(m)
        if len({m["cube"] for m in kept}) > 1:
            entities.append({**e, "members": kept})
    result["entities"] = entities
    result["routing"] = [r for r in result.get("routing", []) if r.get("cube") in profiles]
    return result


# ---------------------------------------------------------------- 3. the layer and its catalog --

_cache = {"mtime": None, "data": {}}
_cache_lock = threading.Lock()


def load() -> dict:
    """The layer ({} if it hasn't been built), cached until the file changes."""
    if not LAYER_FILE.exists():
        return {}
    mtime = LAYER_FILE.stat().st_mtime
    with _cache_lock:
        if _cache["mtime"] != mtime:
            _cache["data"], _cache["mtime"] = json.loads(LAYER_FILE.read_text(encoding="utf-8")), mtime
        return _cache["data"]


def save(layer: dict) -> None:
    LAYER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LAYER_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(layer, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LAYER_FILE)
    CATALOG_FILE.write_text(catalog_text(layer), encoding="utf-8")


def is_built() -> bool:
    return bool(load().get("cubes"))


def layer_cubes() -> list[str]:
    """Cubes in the layer that are still connected, in the admin's order."""
    inside = load().get("cubes", {})
    return [c for c in cubes.enabled() if c in inside]


def status() -> dict:
    """What an admin needs to know: built when, which connected cubes are missing or changed."""
    layer = load()
    inside = layer.get("cubes", {})
    connected = cubes.enabled()
    changed = []
    for c in connected:
        f = cubes.schema_file(c)
        if c in inside and f.exists() and fingerprint(f.read_text(encoding="utf-8")) != inside[c].get("fingerprint"):
            changed.append(c)
    return {"built": layer.get("built", ""), "model": layer.get("model", ""),
            "cubes": [c for c in connected if c in inside], "missing": [c for c in connected if c not in inside],
            "changed": changed, "entities": len(layer.get("entities", [])),
            "ready": bool(inside) and not [c for c in connected if c not in inside]}


def profile(cube: str) -> dict:
    return load().get("cubes", {}).get(cube, {})


def cube_label(cube: str) -> str:
    return profile(cube).get("label") or cubes.label(cube)


def example_questions(limit: int = 6) -> list[str]:
    """Questions for the Chat page: a few that combine cubes, then each cube's own."""
    layer = load()
    out = list(layer.get("cross_cube_questions", []))[:2]
    for c in layer_cubes():
        out += profile(c).get("example_questions", [])[:1]
    return list(dict.fromkeys(out))[:limit]


def catalog_text(layer: dict | None = None, only: list[str] | None = None) -> str:
    """The layer written for Claude (only some cubes, if given)."""
    layer = layer if layer is not None else load()
    if not layer.get("cubes"):
        return ""
    names = [c for c in (only or layer["cubes"]) if c in layer["cubes"]]
    lang = layer.get("language", "DAX")
    lines = [f"# Data layer ({len(names)} cube{'s' if len(names) != 1 else ''}, built {layer.get('built', '')[:10]})"]
    if lang == "DAX":
        lines.append("Each cube is a separate Analysis Services database. One DAX query reads one cube. To combine "
                     "cubes, query each one and join the results on a shared dimension (listed below).")
    routing = [r for r in layer.get("routing", []) if r["cube"] in names]
    if routing:
        lines += ["", "## Which cube for what"]
        lines += [f"- {r['topic']}: {cubes.label(r['cube'])} - {r['why']}" for r in routing]
    lines += ["", "## Cubes"]
    for cube in names:
        p = layer["cubes"][cube]
        lines += ["", f"### {p.get('label') or cubes.label(cube)} - cube \"{cube}\""]
        lines.append(f"{p.get('description', '')} Grain: {p.get('grain', '')}")
        if p.get("use_for"):
            lines.append("Use for: " + "; ".join(p["use_for"]))
        if p.get("not_for"):
            lines.append("Not for: " + "; ".join(p["not_for"]))
        dates = [f"{d['column']} = {d['meaning']}" + (" (default)" if d["column"] == p.get("default_date") else "")
                 for d in p.get("dates", [])]
        if dates:
            lines.append("Dates: " + " · ".join(dates))
        ms = []
        for m in p.get("measures", []):
            syn = f"; also {', '.join(m['synonyms'][:4])}" if m.get("synonyms") else ""
            ms.append(f"{m['name']} {m['label']} ({m['unit']}, {m['aggregation'].replace('_', '-')}{syn})")
        if ms:
            lines.append("Measures: " + " · ".join(ms))
        if p.get("variants"):
            lines.append("Variants: " + p["variants"])
        dims = []
        for d in p.get("dimensions", []):
            cols = ", ".join(x for x in (d.get("key_column") and f"key {d['key_column']}",
                                         d.get("name_column") and d["name_column"] != d.get("key_column")
                                         and f"name {d['name_column']}") if x)
            dims.append(f"{d['entity']} '{d['table']}'" + (f" ({cols})" if cols else ""))
        if dims:
            lines.append("Dimensions: " + " · ".join(dims))
        if p.get("filters"):
            lines.append("Filters: " + " · ".join(f"{f['meaning']} = {f['filter']}" for f in p["filters"]))
        agreed = [r for r in glossary.load(cube)[0] if r.get("Status") == "Agreed"]
        if agreed:
            lines.append("Agreed meanings: " + " · ".join(
                f"{r['Term']} = {r.get('Measure') or r.get('Meaning')}" for r in agreed))
    shared = []
    for e in layer.get("entities", []):
        members = [m for m in e["members"] if m["cube"] in names]
        if len({m["cube"] for m in members}) < 2:
            continue
        parts = [f"{cubes.label(m['cube'])} {m['join_column']}" + (" (names only)" if m["match"] == "names_only" else "")
                 for m in members]
        shared.append(f"- {e['label']}: " + " · ".join(parts) + (f". {e['join_notes']}" if e.get("join_notes") else ""))
    if shared:
        lines += ["", "## Shared dimensions (join keys across cubes)"] + shared
    return "\n".join(lines) + "\n"


_measure_words = {"key": None, "words": set()}


def is_measure_word(phrase: str) -> bool:
    """True when the phrase names a number in some cube ("sales", "bookings", "room nights")."""
    layer = load()
    if _measure_words["key"] != layer.get("built"):
        words = set()
        for p in layer.get("cubes", {}).values():
            for m in p.get("measures", []):
                for w in [m.get("label", "")] + list(m.get("synonyms", [])) + [m.get("name", "").strip("[]")]:
                    if w:
                        words.add(" ".join(w.lower().split()))
        _measure_words.update(key=layer.get("built"), words=words)
    return " ".join(phrase.lower().split()) in _measure_words["words"]


def measure_notes(cube_names: list[str], query: str) -> str:
    """What the numbers in a query are (business name, unit, meaning), for formatting its chart:
    each cube's description (it names the currency) and the measures the query uses."""
    lines = []
    for cube in cube_names:
        p = profile(cube)
        if not p:
            continue
        used = [m for m in p.get("measures", []) if m["name"] in query]
        lines.append(f"{p.get('label') or cubes.label(cube)}: {p.get('description', '')}")
        lines += [f"- {m['name']} = {m['label']}: {m['unit']}, {m['aggregation'].replace('_', '-')}. {m['meaning']}"
                  for m in used]
        if p.get("variants"):
            lines.append(f"- Variant measures: {p['variants']}")
    return "\n".join(lines)


def cube_details(cube: str) -> str:
    """Everything about one cube for writing its query: exact structure and values (physical layer),
    the business notes and glossary."""
    backend = get_backend(cube)
    text = backend.schema_text()
    if not text:
        return f"The cube {cube} has not been read yet."
    notes = glossary.notes_for_claude(cube)
    import semantic
    meaning = semantic.details_text(cube)
    return (text + ("\n## Business notes and glossary\n" + notes if notes.strip() else "")
            + ("\n\n" + meaning if meaning else ""))


# ---------------------------------------------------------------- building --

def build(cube_names: list[str] | None = None, reread: bool = True, only_changed: bool = False,
          on_progress=None) -> dict:
    """Read every cube, profile it with Claude, find the shared dimensions, and save the layer.
    reread=False uses each cube's last read structure; only_changed=True keeps the profiles of
    cubes whose structure hasn't changed. on_progress(text) reports each step. Recorded in usage as one
    "layer_build" (its Claude calls and cost)."""
    with usage.track("layer_build", f"{len(cube_names or cubes.enabled())} cube(s)"):
        return _build(cube_names, reread, only_changed, on_progress)


def _build(cube_names, reread, only_changed, on_progress) -> dict:
    say = on_progress or (lambda text: None)
    names = cube_names or cubes.enabled()
    if not names:
        raise RuntimeError("No cube is connected yet. Tick the cubes to use on the Cubes page first.")
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("No Claude API key is set. Add it on the Settings page.")
    old = load()
    language = get_backend(names[0]).language
    errors = {}

    # 1. physical layer: structure and values of every cube
    def read(cube):
        backend = get_backend(cube)
        if reread or not backend.schema_file.exists():
            backend.refresh_schema()
        return cube
    say(f"Reading the structure and values of {len(names)} cube(s)...")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(read, c): c for c in names}
        for i, f in enumerate(as_completed(futures), 1):
            cube = futures[f]
            try:
                f.result()
                say(f"✓ Read {cubes.label(cube)} ({i}/{len(names)})")
            except Exception as exc:
                errors[cube] = f"Could not read it: {str(exc).splitlines()[0][:200]}"
                say(f"✗ {cubes.label(cube)}: {errors[cube]}")
    names = [c for c in names if c not in errors]

    # 2a. semantic layer: one profile per cube
    schemas = {c: get_backend(c).schema_text() for c in names}
    profiles = {}

    def prof(cube):
        before = old.get("cubes", {}).get(cube)
        if only_changed and before and before.get("fingerprint") == fingerprint(schemas[cube]):
            return before
        return {**profile_cube(cube, schemas[cube], language), "fingerprint": fingerprint(schemas[cube]),
                "profiled": datetime.now().isoformat(timespec="seconds")}
    say(f"Claude is studying each cube ({len(names)})...")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(usage.in_thread(prof), c): c for c in names}
        for i, f in enumerate(as_completed(futures), 1):
            cube = futures[f]
            try:
                profiles[cube] = f.result()
                say(f"✓ Understood {profiles[cube].get('label') or cubes.label(cube)} ({i}/{len(names)})")
            except Exception as exc:
                errors[cube] = f"Claude could not profile it: {str(exc).splitlines()[0][:200]}"
                say(f"✗ {cubes.label(cube)}: {errors[cube]}")
    if not profiles:
        raise RuntimeError("No cube could be read or profiled. " + " ".join(errors.values())[:500])
    profiles = {c: profiles[c] for c in names if c in profiles}  # the admin's order

    # 2b. shared dimensions, measured on the values
    say("Matching customers, suppliers, hotels... across cubes")
    sets = _value_sets(list(profiles))
    members = entity_members(profiles, sets)
    in_entities = {(m["cube"], m[k]) for ms in members.values() for m in ms for k in ("key_column", "name_column")}
    links = column_links(sets, in_entities)
    shared = conform(profiles, members, links) if len(profiles) > 1 else {}

    layer = {"version": VERSION, "built": datetime.now().isoformat(timespec="seconds"),
             "model": config.CLAUDE_LAYER_MODEL, "language": language,
             "source": config.resolve_source(), "server": config.SSAS_SERVER if language == "DAX" else "data/local",
             "cubes": profiles, "entities": shared.get("entities", []), "routing": shared.get("routing", []),
             "cross_cube_questions": shared.get("cross_cube_questions", []),
             "evidence": {"members": members, "links": links}, "errors": errors}
    save(layer)
    say(f"Saved the data layer: {len(profiles)} cube(s), {len(layer['entities'])} shared dimension(s).")
    return layer
