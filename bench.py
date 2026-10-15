"""Benchmark: asks a fixed set of real questions the same way Chat does, and records for each one the
time, the Claude calls, tokens and cost, and a fingerprint of the answer; it also measures the Chat
page itself. Compare two runs to see what a change did - in speed, cost and answers.

Run:  python bench.py run before                 (saves data/bench/before.json; uses Claude and the server)
      python bench.py run after
      python bench.py run before-joins joins     (the harder set: joins across cubes, names, comparisons)
      python bench.py compare before after       (prints the difference; saves data/bench/compare.md)
"""
import json
import statistics
import sys
import time
from datetime import datetime

import pandas as pd

import config
import usage

QUESTIONS = [
    "Top 10 customers by sales this year",
    "How many bookings were made last month?",
    "Sales and profit by month this year",
    "Number of bookings by sale channel this year",
    "Payments collected by payment type this year",
    "Top 10 suppliers by number of bookings last month",
    "Top 10 customers by number of API requests yesterday",
    "Allotment usage by hotel this month, top 10 hotels",
    "For the top 10 customers by sales this year, show their sales next to their payments",
    "Bookings from the UAE market by month this year",
    "Ticket sales by service this year",
    "Top 10 customers by sales this year",  # asked again: shows what repeating a question costs
]
# Harder questions: joins across cubes, names of customers / suppliers / hotels, comparisons.
JOIN_QUESTIONS = [
    "For the top 10 customers by sales this year, show their bookings, sales and payments collected",
    "Look-to-book ratio and number of bookings by market last month",
    "Hotelbeds bookings and sales by month this year compared with the same months last year",
    "Which 10 suppliers had the most hotel locks last month, and how many bookings did they get?",
    "Top 10 suppliers by sales this year with their price change rate and profit",
    "Bookings and sales for Cozmo Travel Kuwait by month this year",
    "Top 10 destinations by hotel searches this year with their bookings and sales",
    "Allotment utilisation for the top 10 hotels by used allotment this month, with their hotel sales",
    "Cancellation rate and profit margin by country for owned hotels this year vs last year",
    "Payment success rate by sale channel last month next to the number of bookings and sales",
]
SETS = {"standard": QUESTIONS, "joins": JOIN_QUESTIONS}
WARM_UP = "How many bookings were made yesterday?"  # asked first, not recorded: both runs start with a warm cache
BENCH_DIR = config.DATA_DIR / "bench"


def private_memory_mb() -> float | None:
    """This process's private memory (Windows), as Task Manager's "Memory" column shows it."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("faults", wt.DWORD)] + [(f"f{i}", ctypes.c_size_t) for i in range(8)] \
                       + [("private", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return round(c.private / 2**20)
    except Exception:
        return None


def fingerprint(outcome) -> dict:
    """Enough of an answer to tell whether two runs answered the same way."""
    out = {"kind": outcome.kind, "understanding": outcome.result.get("understanding", "")[:300]}
    if outcome.kind == "clarify":
        out["asked"] = outcome.question
    df = outcome.df
    if df is not None:
        nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        out.update(rows=len(df), columns=[str(c) for c in df.columns],
                   totals={str(c): float(df[c].sum()) for c in nums},
                   first_row=[str(v) for v in df.iloc[0].tolist()] if len(df) else [],
                   cubes=outcome.plan.cubes if outcome.plan else [],
                   plan=outcome.plan.text()[:4000] if outcome.plan else "",
                   chart=outcome.spec.get("chart_type", ""), summary=outcome.spec.get("summary", "")[:300])
    return out


def chat_page() -> dict:
    """Time the Chat page's own work on a click, and how much it sends to the browser."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=120)
    at.run()
    at.switch_page("views/chat.py").run()
    times = []
    for _ in range(3):
        started = time.perf_counter()
        at.run()
        times.append(time.perf_counter() - started)
    sent = sum(len(str(m.value)) for m in at.markdown) + sum(len(str(c.value)) for c in at.caption)
    return {"seconds_per_click": round(statistics.median(times), 3), "characters_sent": sent,
            "errors": [str(e.value)[:200] for e in at.exception]}


def run(label: str, question_set: str = "standard") -> None:
    import answer_memory
    import answering
    questions = SETS[question_set]
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    for question in set(questions) | {WARM_UP}:  # a fair run: nothing remembered from an earlier run today
        answer_memory.forget_today(question)
    started_mb = private_memory_mb()
    try:
        answering.ask(WARM_UP)
    except Exception:
        pass
    results = []
    for i, question in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {question}", flush=True)
        started = time.perf_counter()
        try:
            outcome = answering.ask(question)
            answer, error = fingerprint(outcome), ""
        except Exception as exc:
            answer, error = {}, f"{type(exc).__name__}: {str(exc)[:300]}"
        seconds = time.perf_counter() - started
        entry = next((u for u in reversed(usage.load(limit=20)) if u.get("label") == question), {})
        results.append({"question": question, "seconds": round(seconds, 1), "error": error, "answer": answer,
                        **{k: entry.get(k) for k in ("cost", "claude_calls", "claude_seconds", "input_tokens",
                                                     "output_tokens", "cache_read_tokens", "cache_write_tokens",
                                                     "cache_hit", "stages", "calls")}})
        r = results[-1]
        print(f"      {r['seconds']:.0f}s  ${r['cost'] or 0:.3f}  {r['claude_calls']} Claude calls  "
              f"{answer.get('kind', 'error')}  {error}", flush=True)
    memory = {"at_start_mb": started_mb, "after_questions_mb": private_memory_mb()}
    page = chat_page()
    data = {"label": label, "time": datetime.now().isoformat(timespec="seconds"), "model": config.CLAUDE_MODEL,
            "set": question_set, "questions": results, "memory": memory, "chat_page": page}
    (BENCH_DIR / f"{label}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {BENCH_DIR / (label + '.json')}  ·  Memory: {memory}  ·  Chat page: {page}")


def _same(a: dict, b: dict) -> str:
    """'same' (the same numbers; one answer may show an extra column), 'close' (within 2%: the cube
    may have refreshed between runs) or 'different'."""
    if not a or not b or a.get("kind") != b.get("kind"):
        return "different"
    if a["kind"] != "data":
        return "same"
    if a.get("rows") != b.get("rows"):
        return "different"
    near = lambda x, y, tol: abs(x - y) <= tol * max(abs(x), abs(y), 1)
    small, big = sorted([list(a.get("totals", {}).values()), list(b.get("totals", {}).values())], key=len)
    if not small:
        return "same"
    if all(any(near(x, y, 1e-9) for y in big) for x in small):
        return "same"
    return "close" if all(any(near(x, y, 0.02) for y in big) for x in small) else "different"


def compare(before: str, after: str) -> str:
    a, b = (json.loads((BENCH_DIR / f"{n}.json").read_text(encoding="utf-8")) for n in (before, after))
    lines = [f"| # | Question | Time {before} → {after} | Cost {before} → {after} | Claude calls | Answer |",
             "|---|---|---|---|---|---|"]
    for i, (x, y) in enumerate(zip(a["questions"], b["questions"]), 1):
        lines.append(f"| {i} | {x['question']} | {x['seconds']:.0f}s → {y['seconds']:.0f}s | "
                     f"${x['cost'] or 0:.3f} → ${y['cost'] or 0:.3f} | {x['claude_calls']} → {y['claude_calls']} | "
                     f"{_same(x['answer'], y['answer'])} |")
    med = lambda run, key: statistics.median([q[key] or 0 for q in run["questions"]])
    tot = lambda run, key: sum(q[key] or 0 for q in run["questions"])
    read_all = lambda run: sum((q["cache_read_tokens"] or 0) + (q["input_tokens"] or 0) + (q["cache_write_tokens"] or 0)
                               for q in run["questions"])
    fresh = lambda run: sum((q["input_tokens"] or 0) + (q["cache_write_tokens"] or 0) for q in run["questions"])
    mem = lambda run: f"{run['memory']['after_questions_mb']:,} MB" if run.get("memory", {}).get("after_questions_mb") else "-"
    lines += ["", f"| | {before} | {after} |", "|---|---|---|",
              f"| Median time per question | {med(a, 'seconds'):.0f}s | {med(b, 'seconds'):.0f}s |",
              f"| Total time ({len(a['questions'])} questions) | {tot(a, 'seconds') / 60:.1f} min | {tot(b, 'seconds') / 60:.1f} min |",
              f"| Average cost per question | ${tot(a, 'cost') / len(a['questions']):.3f} | ${tot(b, 'cost') / len(b['questions']):.3f} |",
              f"| Total cost | ${tot(a, 'cost'):.2f} | ${tot(b, 'cost'):.2f} |",
              f"| Claude calls | {tot(a, 'claude_calls')} | {tot(b, 'claude_calls')} |",
              f"| Tokens Claude read (all questions) | {read_all(a):,} | {read_all(b):,} |",
              f"| ...of which not from the cache (full price or more) | {fresh(a):,} | {fresh(b):,} |",
              f"| Tokens Claude wrote (incl. thinking) | {tot(a, 'output_tokens'):,} | {tot(b, 'output_tokens'):,} |",
              f"| Memory after the questions | {mem(a)} | {mem(b)} |",
              f"| Chat page: time per click | {a['chat_page']['seconds_per_click']:.2f}s | {b['chat_page']['seconds_per_click']:.2f}s |",
              f"| Chat page: characters sent per click | {a['chat_page']['characters_sent']:,} | {b['chat_page']['characters_sent']:,} |"]
    text = "\n".join(lines)
    (BENCH_DIR / "compare.md").write_text(text + "\n", encoding="utf-8")
    return text


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else "standard")
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        print(compare(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
