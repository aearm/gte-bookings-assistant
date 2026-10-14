"""Usage (admins only): what questions cost and how long they take - from data/usage.jsonl, written by
usage.py for every question - and the benchmark comparisons from bench.py."""
import json
import statistics
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import admin
import bench
import usage

st.title("Usage")
st.caption("How long questions take and what they cost in Claude, per question and per stage.")
if not admin.signed_in():
    admin.locked_page("The Usage page")

rows = usage.load(kind="question")
week_ago = (datetime.now() - timedelta(days=7)).isoformat()
recent = [r for r in rows if r.get("time", "") >= week_ago]
if not rows:
    st.info("No questions measured yet. Ask something in Chat.")
else:
    a, b, c, d = st.columns(4)
    a.metric("Questions (7 days)", f"{len(recent):,}")
    b.metric("Median time", f"{statistics.median(r['seconds'] for r in recent or rows):.0f} s")
    c.metric("Average cost", f"${sum(r['cost'] for r in recent or rows) / len(recent or rows):.3f}")
    d.metric("Cost (7 days)", f"${sum(r['cost'] for r in recent):.2f}")
    remembered = sum(1 for r in recent if r.get("memory"))
    st.caption(f"{remembered} of {len(recent)} questions this week were repeats answered from memory "
               "(no Claude call for the plan).")

    table = pd.DataFrame([{
        "When": r["time"].replace("T", " ")[:16], "Question": r["label"], "Seconds": r["seconds"],
        "Cost ($)": r["cost"], "Claude calls": r["claude_calls"], "From cache": r.get("cache_hit", 0),
        "Answer": r.get("outcome", r.get("error", "")[:40]), "Memory": "yes" if r.get("memory") else "",
        **{f"{k} (s)": v for k, v in (r.get("stages") or {}).items()}} for r in reversed(rows[-300:])])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Cost ($)": st.column_config.NumberColumn(format="$%.3f"),
        "From cache": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})

runs = sorted(bench.BENCH_DIR.glob("*.json")) if bench.BENCH_DIR.exists() else []
if len(runs) >= 2:
    st.subheader("Benchmark")
    names = [p.stem for p in runs]
    left, right = st.columns(2)
    before = left.selectbox("Before", names, index=0)
    after = right.selectbox("After", names, index=len(names) - 1)
    if before != after:
        st.markdown(bench.compare(before, after))
        with st.expander("Answers side by side"):
            x, y = (json.loads((bench.BENCH_DIR / f"{n}.json").read_text(encoding="utf-8")) for n in (before, after))
            for qa, qb in zip(x["questions"], y["questions"]):
                st.markdown(f"**{qa['question']}**")
                cols = st.columns(2)
                cols[0].caption(qa["answer"].get("summary") or qa["answer"].get("asked") or qa["error"])
                cols[1].caption(qb["answer"].get("summary") or qb["answer"].get("asked") or qb["error"])
