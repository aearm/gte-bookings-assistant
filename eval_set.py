"""A hard, fixed test set for the whole answering pipeline: questions that join 1 to 5 cubes and ask
for different charts, over fixed past periods (never today - the cubes are live), each checked
against reference numbers from simple one-measure queries run at the same time (so slow changes in
old data can't make a correct answer look wrong).

The questions are company data, so they live in data/eval/questions.json (not in git):
  {"questions": [{"id": "Q01", "question": "...", "cubes": ["GlobalTravelEngine - Bookings"],
                  "chart": {"types": ["line"], "measures": 2, "layout": ""},
                  "checks": [<check>, ...]}]}
A check is a reference number the answer must contain:
  {"name": "Sales Q3", "cube": "...", "measure": "[Sale]", "date": "'Calendar'[Date]",
   "from": "2026-07-01", "to": "2026-09-30", "kind": "total"}   a column of the answer adds up to it
  {..., "kind": "top", "n": 10, "by": "'Customers'[Code]"}       a column holds these top-N values
  {..., "kind": "top_sum", "n": 10, "by": "..."}                 a column adds up to the top N's total
  "period": "Last month" instead of from/to: relative to the day the test runs (periods.PRESETS)
chart: "types" allowed, at least "measures" numbers drawn, "layout" "panels" | "one_chart" | "".
Optional per question: "turns": earlier messages asked first, as in a chat (the question is a follow-up);
"expect": "clarify" when the right answer is a question back; "tags": groups for the report
(paraphrase, follow_up, relative_dates, clarify, holdout).

Run:  python eval_set.py refs                 the reference numbers only (checks the set itself; no Claude)
      python eval_set.py run <label>          asks every question; saves data/eval/results/<label>.json and .md
      python eval_set.py run <label> Q04 Q16  asks only these again, keeping the other results
      python eval_set.py run <label> --repeat 3   each question 3 times (rates with 95% ranges)
      python eval_set.py compare <a> <b>"""
import json
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd

import config
import usage

EVAL_DIR = config.DATA_DIR / "eval"
RESULTS = EVAL_DIR / "results"
TOLERANCE = 0.001  # a tenth of a percent: right answers match exactly; near misses are different numbers


def load() -> list[dict]:
    return json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))["questions"]


# ---------------------------------------------------------------- reference numbers --

def _dax_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"DATE({d.year},{d.month},{d.day})"


def check_dates(check: dict) -> tuple[str, str]:
    """(first, last day) of a check: fixed ("from", "to") or relative to today ("period": "Last month")."""
    if check.get("period"):
        import periods
        start, end = periods.preset_range(check["period"])
        return start.isoformat(), (end - timedelta(days=1)).isoformat()
    return check["from"], check["to"]


def reference_query(check: dict) -> str:
    col = check["date"]
    first, last = check_dates(check)
    period = (f"KEEPFILTERS(FILTER(ALL({col}), {col} >= {_dax_date(first)} && "
              f"{col} <= {_dax_date(last)}))")
    where = f", {check['where']}" if check.get("where") else ""
    if check["kind"] == "total":
        return f'EVALUATE SUMMARIZECOLUMNS({period}{where}, "v", {check["measure"]})'
    import value_index
    info = value_index.for_cube(check["cube"]).column_info(check["by"]) or {}
    cols = ", ".join(info.get("group_with", []) + [check["by"]])
    n = int(check["n"]) + (2 if check["kind"] == "top" else 0)  # room for an "Unknown" the answer may leave out
    return (f'EVALUATE TOPN({n}, SUMMARIZECOLUMNS({cols}, {period}{where}, "v", {check["measure"]}), [v], DESC) '
            "ORDER BY [v] DESC")


def reference(check: dict):
    """The number (total, top_sum) or numbers (top, biggest first) the answer must contain."""
    from backends import get_backend
    df = get_backend(check["cube"]).run(reference_query(check), None)
    values = [float(v) for v in df.iloc[:, -1].dropna()] if len(df) else []
    if check["kind"] == "total":
        return values[0] if values else 0.0
    values.sort(reverse=True)
    return sum(values[:int(check["n"])]) if check["kind"] == "top_sum" else values


# ---------------------------------------------------------------- checking an answer --

def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(abs(b) * TOLERANCE, 0.5)


def _numbers(df: pd.DataFrame) -> list[str]:
    import charts
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not charts.is_time_column(df[c])]


def check_data(df: pd.DataFrame | None, check: dict, ref) -> dict:
    """Does a column of the answer hold the reference number(s)? Also the closest it came."""
    if df is None or df.empty:
        return {"ok": False, "why": "no data"}
    cols = _numbers(df)
    if check["kind"] in ("total", "top_sum"):
        sums = {c: float(df[c].sum()) for c in cols}
        # also within one group of a short column, e.g. the 2026 rows of a table with 2025 and 2026 in it
        for g in [c for c in df.columns if c not in cols and 1 < df[c].nunique() <= 12]:
            for value, part in df.groupby(g):
                sums.update({f"{c} where {g} = {value}": float(part[c].sum()) for c in cols})
        hit = next((c for c, s in sums.items() if _close(s, ref)), None)
        near = min(sums.items(), key=lambda cs: abs(cs[1] - ref), default=(None, None))
        return {"ok": hit is not None, "column": hit or near[0], "found": sums.get(hit) if hit else near[1]}
    n = int(check["n"])
    best = (None, 0)
    for c in cols:
        values = sorted(df[c].dropna().astype(float), reverse=True)[:n]
        matched = sum(any(_close(v, r) for r in ref) for v in values)
        if matched > best[1]:
            best = (c, matched)
    return {"ok": best[1] >= max(1, n - 1), "column": best[0], "found": f"{best[1]} of top {n}"}


def check_chart(df: pd.DataFrame | None, spec: dict, want: dict) -> dict:
    """Is it drawn the way the question asked: the type, every measure, panels or one chart?"""
    import charts
    if df is None or df.empty:
        return {"ok": False, "why": "no data"}
    fitted = charts.fit(df, spec)
    kind = fitted["chart_type"]
    if want["types"] == ["table"]:
        return {"ok": kind == "table", "why": "" if kind == "table" else f"{kind} instead of a table", "type": kind}
    try:
        fig = charts.build_figure(df, spec)
    except Exception as exc:
        return {"ok": False, "why": f"drawing failed: {exc}", "type": kind}
    if fig is None:
        return {"ok": False, "why": "drawn as a table", "type": "table"}
    problems = []
    if kind not in want["types"]:
        problems.append(f"{kind} instead of {'/'.join(want['types'])}")
    if kind == "custom":
        import dynamic_chart
        drawn = len(dynamic_chart.columns_used(spec["custom"]) & set(_numbers(df)))
    else:
        drawn = len(fitted["y"])
    if drawn < want.get("measures", 0):
        problems.append(f"{drawn} of {want['measures']} measures drawn")
    layout = fig.layout.to_plotly_json()
    axes = [k for k in layout if k.startswith("yaxis")]
    overlaid = [k for k in axes if layout[k].get("overlaying")]
    if want.get("layout") == "one_chart" and not overlaid:
        problems.append("not one chart with an axis per measure")
    if want.get("layout") == "panels" and len(axes) - len(overlaid) < 2:
        problems.append("not one panel per measure")
    return {"ok": not problems, "why": "; ".join(problems), "type": kind, "measures": drawn}


# ---------------------------------------------------------------- running --

def refs() -> dict:
    out = {}
    for q in load():
        for check in q["checks"]:
            try:
                value = reference(check)
            except Exception as exc:
                value = f"FAILED: {str(exc).splitlines()[0][:200]}"
            out[f"{q['id']} {check['name']}"] = value
            shown = value if isinstance(value, str) else (f"{value:,.2f}" if isinstance(value, float)
                                                          else ", ".join(f"{v:,.0f}" for v in value[:5]) + " ...")
            print(f"{q['id']} {check['name']:45} {shown}", flush=True)
    return out


def version() -> dict:
    """What was tested: the code, the models, the prompts and the meaning layer (to tell runs apart)."""
    import hashlib
    import subprocess
    import llm
    import rewrite
    import routing
    import semantic

    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=config.BASE_DIR, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
        except Exception:
            return ""
    prompts = "".join([llm.PLAN_RULES, llm.DAX_RULES, llm.CHECK_RULES, llm.FORMAT_RULES, llm.DYNAMIC_RULES,
                       rewrite.RULES, routing.ROUTE_RULES])
    layer = "".join(p.read_text(encoding="utf-8") for p in sorted((semantic.SEMANTIC_DIR / "cubes").glob("*.json")))
    return {"git": git("rev-parse", "--short", "HEAD") + ("+changes" if git("status", "--porcelain") else ""),
            "model": config.CLAUDE_MODEL, "fast_model": config.CLAUDE_FAST_MODEL,
            "prompts": hashlib.sha256(prompts.encode()).hexdigest()[:10],
            "meaning_layer": f"{semantic.VERSION}/{hashlib.sha256(layer.encode()).hexdigest()[:10]}"}


def _stage(result: dict) -> str:
    """Where a trial first went wrong ("" when it passed)."""
    if result["pass"]:
        return ""
    if result["expect"] == "clarify":
        return "answered instead of asking" if result["outcome"] in ("data", "reuse") else "error"
    if result["outcome"] == "error":
        e = result["error"]
        return ("earlier turn" if "Earlier turn" in e else "API" if "Error code" in e or "APIStatus" in e
                else "query" if e.startswith(("StepError", "Query", "AdomdErrorResponseException")) else "plan")
    if result["outcome"] == "clarify":
        return "asked instead of answering"
    return "cubes" if not result["cubes_ok"] else "numbers" if not result["data_ok"] else "chart"


def _ask_conversation(q: dict):
    """Ask the question's earlier turns (a follow-up), as Chat does, then the question.
    Returns (outcome, the earlier turns)."""
    import answer_memory
    import answering
    context = []
    for text in q.get("turns", []):
        answer_memory.forget_today(text)
        out = answering.ask(text, context=context or None)
        if out.kind not in ("data", "reuse") or out.df is None:
            raise RuntimeError(f"Earlier turn {text!r} gave {out.kind}: {out.question or ''}")
        turn = {"question": text, "understanding": out.result.get("understanding", ""), "df": out.df, "spec": out.spec}
        if out.kind == "reuse":
            turn.update({k: context[-1][k] for k in ("query", "plan", "cubes") if k in context[-1]})
        else:
            turn.update(query=out.plan.text(), plan=out.plan.to_dict(), cubes=out.plan.cubes)
        context.append(turn)
    answer_memory.forget_today(q["question"])
    return answering.ask(q["question"], context=context or None), context


def trial(q: dict) -> dict:
    """Ask one question once (after its earlier turns) and check the answer."""
    refs_now = {}
    for check in q["checks"]:
        try:
            refs_now[check["name"]] = reference(check)
        except Exception as exc:
            refs_now[check["name"]] = f"FAILED: {str(exc).splitlines()[0][:200]}"
    started = time.perf_counter()
    outcome, error, failed_plan, context = None, "", None, []
    try:
        outcome, context = _ask_conversation(q)
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
        failed_plan = getattr(exc, "plan", None)
    seconds = time.perf_counter() - started
    labels = [*q.get("turns", []), q["question"]]
    entries = [u for u in usage.load(limit=40) if u.get("label") in labels][-len(labels):]
    entry = entries[-1] if entries else {}
    expect = q.get("expect", "data")
    df = outcome.df if outcome and outcome.kind in ("data", "reuse") else None
    data = [{"name": c["name"], "reference": refs_now[c["name"]],
             **(check_data(df, c, refs_now[c["name"]]) if not isinstance(refs_now[c["name"]], str)
                else {"ok": False, "why": "reference failed"})} for c in q["checks"]]
    if df is not None and q.get("chart"):
        chart = check_chart(df, outcome.spec, q["chart"])
    else:
        chart = {"ok": expect == "clarify" or not q.get("chart"), "why": "" if expect == "clarify" else "no data"}
    plan = outcome.plan if outcome and outcome.plan else failed_plan
    used = plan.cubes if plan else []
    result = {
        "id": q["id"], "question": q["question"], "turns": q.get("turns", []), "tags": q.get("tags", []),
        "expect": expect, "cubes_expected": q["cubes"], "cubes_used": used,
        "outcome": outcome.kind if outcome else "error", "error": error,
        "asked": outcome.question if outcome and outcome.kind == "clarify" else "",
        "understanding": (outcome.result.get("understanding", "") if outcome else "")[:400],
        "rewritten": entry.get("rewritten", ""), "periods": entry.get("periods", []),
        "seconds": round(seconds, 1), "cost": round(sum(e.get("cost", 0) for e in entries), 4),
        "claude_calls": sum(e.get("claude_calls", 0) for e in entries),
        "cubes_ok": expect == "clarify" or set(q["cubes"]) <= set(used), "data": data, "chart": chart,
        "plan": plan.text()[:6000] if plan else "",
    }
    result["data_ok"] = all(d["ok"] for d in data)
    if expect == "clarify":
        result["pass"] = result["outcome"] == "clarify"
    else:
        result["pass"] = (result["outcome"] in ("data", "reuse") and result["cubes_ok"] and result["data_ok"]
                          and chart["ok"])
    result["stage"] = _stage(result)
    return result


def run(label: str, only: list[str] | None = None, repeat: int = 1) -> None:
    """Ask every question (or only some, replacing their results in an existing run) `repeat` times."""
    questions = [q for q in load() if not only or q["id"] in only]
    earlier = RESULTS / f"{label}.json"
    kept = json.loads(earlier.read_text(encoding="utf-8"))["results"] if only and earlier.exists() else []
    results = []
    for i, q in enumerate(questions, 1):
        for k in range(repeat):
            print(f"[{i}/{len(questions)}{f' #{k + 1}' if repeat > 1 else ''}] {q['id']} ({len(q['cubes'])} "
                  f"cube{'s' if len(q['cubes']) != 1 else ''}) {q['question'][:80]}", flush=True)
            r = {**trial(q), "trial": k + 1}
            results.append(r)
            print(f"      {'PASS' if r['pass'] else 'FAIL ' + r['stage']}  {r['seconds']:.0f}s  ${r['cost'] or 0:.3f}  "
                  f"data {sum(d['ok'] for d in r['data'])}/{len(r['data'])}  "
                  f"chart {'ok' if r['chart']['ok'] else r['chart'].get('why', '')}  {r['error'] or r['asked'][:80]}",
                  flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if kept:  # some questions asked again: the others keep their results, in the set's order
        order = [q["id"] for q in load()]
        asked = {r["id"] for r in results}
        results = sorted([r for r in kept if r["id"] not in asked] + results,
                         key=lambda r: (order.index(r["id"]) if r["id"] in order else 999, r.get("trial", 1)))
    data = {"label": label, "time": datetime.now().isoformat(timespec="seconds"), "model": config.CLAUDE_MODEL,
            "version": version(), "repeat": repeat, "results": results}
    (RESULTS / f"{label}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (RESULTS / f"{label}.md").write_text(report(data), encoding="utf-8")
    print(report(data))


# ---------------------------------------------------------------- reporting --

def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval of a pass rate (Wilson score): with few questions a rate is a range, not a number."""
    if not n:
        return 0.0, 0.0
    p = passed / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _by_question(rs: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for r in rs:
        out.setdefault(r["id"], []).append(r)
    return out


def _rate(trials: list[dict]) -> str:
    passed, n = sum(r["pass"] for r in trials), len(trials)
    low, high = wilson(passed, n)
    return f"{passed}/{n} ({passed / max(n, 1):.0%}, 95% {low:.0%}-{high:.0%})"


def report(data: dict) -> str:
    rs = data["results"]
    qs = _by_question(rs)
    v = data.get("version", {})
    lines = [f"# {data['label']} ({data['model']}, {data['time']})", "",
             f"Code {v.get('git', '?')} · prompts {v.get('prompts', '?')} · meaning layer {v.get('meaning_layer', '?')}"
             f" · {data.get('repeat', 1)} trial(s) per question", "",
             "| Q | Cubes | Tags | Passed | Went wrong | Cost | Time |", "|---|---|---|---|---|---|---|"]
    for qid, trials in qs.items():
        stages = sorted({r.get("stage", "") for r in trials} - {""})
        bad = next((r for r in trials if not r["pass"]), trials[0])
        detail = (bad["error"] or bad["asked"] or bad["chart"].get("why", ""))[:60]
        why = "; ".join(stages) + (f" ({detail})" if stages and detail else "")
        lines.append(f"| {qid} | {len(trials[0]['cubes_expected'])} | {', '.join(trials[0].get('tags', []))} | "
                     f"{sum(r['pass'] for r in trials)}/{len(trials)} | {why} | "
                     f"${sum(r['cost'] or 0 for r in trials) / len(trials):.3f} | "
                     f"{sorted(r['seconds'] for r in trials)[len(trials) // 2]:.0f}s |")
    n, cost = len(rs), sum(r["cost"] or 0 for r in rs)
    times = sorted(r["seconds"] for r in rs)
    every = sum(all(r["pass"] for r in t) for t in qs.values())
    stages = {}
    for r in rs:
        if r.get("stage"):
            stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    lines += ["", f"**Passed {_rate(rs)}** of all trials · {every} of {len(qs)} questions passed every trial · "
                  f"cost ${cost:.2f} (${cost / max(n, 1):.3f} a question) · median {times[n // 2] if n else 0:.0f}s, "
                  f"slowest tenth {times[min(int(n * 0.9), n - 1)] if n else 0:.0f}s", ""]
    if stages:
        lines.append("Where they went wrong: " + " · ".join(f"{k} {c}" for k, c in sorted(stages.items(), key=lambda x: -x[1])))
        lines.append("")
    groups = {}
    for r in rs:
        for g in [f"{len(r['cubes_expected'])} cube{'s' if len(r['cubes_expected']) != 1 else ''}", *r.get("tags", [])]:
            groups.setdefault(g, []).append(r)
    lines.append("By group: " + " · ".join(f"{g} {_rate(t)}" for g, t in sorted(groups.items())))
    return "\n".join(lines) + "\n"


def sign_test(better: int, worse: int) -> float:
    """Two-sided exact sign test: how likely this split of improved vs worse questions is by chance alone."""
    from math import comb
    n, k = better + worse, min(better, worse)
    if not n:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def compare(a: str, b: str) -> str:
    x, y = (json.loads((RESULTS / f"{n}.json").read_text(encoding="utf-8")) for n in (a, b))
    qa, qb = _by_question(x["results"]), _by_question(y["results"])
    lines = [f"| Q | {a} | {b} |", "|---|---|---|"]
    better = worse = 0

    def mark(t):
        return (f"{sum(r['pass'] for r in t)}/{len(t)} ${sum(r['cost'] or 0 for r in t) / len(t):.3f} "
                f"{sorted(r['seconds'] for r in t)[len(t) // 2]:.0f}s")
    for qid in [q for q in qa if q in qb]:
        ra, rb = (sum(r["pass"] for r in t) / len(t) for t in (qa[qid], qb[qid]))
        better, worse = better + (rb > ra), worse + (rb < ra)
        lines.append(f"| {qid} | {mark(qa[qid])} | {mark(qb[qid])}{' ▲' if rb > ra else ' ▼' if rb < ra else ''} |")
    chance = sign_test(better, worse)
    lines += ["", f"{a}: {_rate(x['results'])} · {b}: {_rate(y['results'])}",
              f"{better} questions better, {worse} worse · chance of a split like this with no real change: "
              f"{chance:.0%}" + (" (not a real difference yet)" if chance > 0.05 else "")]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    if sys.argv[1:2] == ["refs"]:
        refs()
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        args = sys.argv[3:]
        repeat = int(args[args.index("--repeat") + 1]) if "--repeat" in args else 1
        ids = [a for i, a in enumerate(args) if a != "--repeat" and (i == 0 or args[i - 1] != "--repeat")]
        run(sys.argv[2], ids or None, repeat)
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        print(compare(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
