"""Saves every answer: the data as CSV plus a history log."""
import json
import re
from datetime import datetime

import pandas as pd

import config


def save_result(question: str, query: str, df: pd.DataFrame, spec: dict) -> str:
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = config.RESULTS_DIR / f"{stamp}_{slugify(question)[:40]}.csv"
    df.to_csv(path, index=False)
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "question": question,
             "query": query, "rows": len(df), "file": str(path.relative_to(config.BASE_DIR)),
             "title": spec.get("title", ""), "summary": spec.get("summary", "")}
    with open(config.HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(path)


def load_history(limit: int = 20) -> list[dict]:
    if not config.HISTORY_FILE.exists():
        return []
    entries = []
    for line in config.HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-limit:][::-1]


def save_query_for_schedule(name: str, dax: str) -> str:
    config.QUERIES_DIR.mkdir(parents=True, exist_ok=True)
    path = config.QUERIES_DIR / f"{slugify(name)[:60]}.dax"
    path.write_text(dax.strip() + "\n", encoding="utf-8")
    return path.name


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "query"
