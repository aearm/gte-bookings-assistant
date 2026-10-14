"""Remembers answered questions (data/answers.db, SQLite):
- the same question again on the same day, about the same data, reruns its saved plan - no Claude call
  for the plan, and none for the chart when the numbers haven't changed;
- answers an admin marks as correct ("verified") are shown to Claude as worked examples for similar
  questions on later days, which makes it faster and more consistent.
Only answers that returned data are kept; clarifying questions and errors are not."""
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime

import config

_lock = threading.Lock()
_STOP = set("""a an and are as at be by for from how i in is it last many me month of on or show than that the
their this to top was were what which with year""".split())


@contextmanager
def _db():
    """A connection to data/answers.db that commits and closes when done."""
    path = config.DATA_DIR / "answers.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, norm TEXT, scope TEXT, day TEXT, layer TEXT,
            plan TEXT, result TEXT, spec TEXT, data_hash TEXT, verified INTEGER DEFAULT 0,
            uses INTEGER DEFAULT 0, created TEXT, last_used TEXT)""")
        con.execute("CREATE INDEX IF NOT EXISTS answers_norm ON answers (norm, scope, day)")
        yield con
        con.commit()
    finally:
        con.close()


def normalize(question: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", question.lower()))


def _words(question: str) -> set[str]:
    return {w for w in normalize(question).split() if w not in _STOP}


def data_hash(df) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()[:16] if df is not None else ""


def _layer_key() -> str:
    import data_layer
    return data_layer.load().get("built", "")


def same_day(question: str, scope: str) -> dict | None:
    """The answer to this exact question today (same data layer), if there is one."""
    with _lock, _db() as con:
        row = con.execute("SELECT * FROM answers WHERE norm = ? AND scope = ? AND day = ? AND layer = ? "
                          "ORDER BY verified DESC, id DESC LIMIT 1",
                          (normalize(question), scope, date.today().isoformat(), _layer_key())).fetchone()
        if row is None:
            return None
        con.execute("UPDATE answers SET uses = uses + 1, last_used = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), row["id"]))
    return {**dict(row), "plan": json.loads(row["plan"]), "result": json.loads(row["result"]),
            "spec": json.loads(row["spec"])}


def remember(question: str, scope: str, plan: dict, result: dict, spec: dict, df) -> int:
    keep = {k: result.get(k, "") for k in ("understanding", "explanation", "chart_request")}
    with _lock, _db() as con:
        cur = con.execute("INSERT INTO answers (question, norm, scope, day, layer, plan, result, spec, data_hash, created) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (question, normalize(question), scope, date.today().isoformat(), _layer_key(),
                           json.dumps(plan, ensure_ascii=False), json.dumps(keep, ensure_ascii=False),
                           json.dumps(spec, ensure_ascii=False, default=str), data_hash(df),
                           datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid


def forget_today(question: str, scope: str = "") -> None:
    """Drop today's unverified answers to a question (e.g. before a benchmark run)."""
    with _lock, _db() as con:
        con.execute("DELETE FROM answers WHERE norm = ? AND scope = ? AND day = ? AND verified = 0",
                    (normalize(question), scope, date.today().isoformat()))


def update_spec(answer_id: int, spec: dict, df) -> None:
    with _lock, _db() as con:
        con.execute("UPDATE answers SET spec = ?, data_hash = ? WHERE id = ?",
                    (json.dumps(spec, ensure_ascii=False, default=str), data_hash(df), answer_id))


def verify(answer_id: int, verified: bool = True) -> None:
    """An admin confirmed (or withdrew) that this answer is right."""
    with _lock, _db() as con:
        con.execute("UPDATE answers SET verified = ? WHERE id = ?", (1 if verified else 0, answer_id))


def examples(question: str, scope: str, limit: int = 2) -> list[dict]:
    """Verified answers to similar questions (most words in common), as worked examples."""
    words = _words(question)
    if not words:
        return []
    with _lock, _db() as con:
        rows = con.execute("SELECT question, plan, result, scope FROM answers WHERE verified = 1 AND layer = ? "
                           "ORDER BY id DESC LIMIT 500", (_layer_key(),)).fetchall()
    scored = []
    for r in rows:
        other = _words(r["question"])
        similarity = len(words & other) / len(words | other) if other else 0
        if similarity >= 0.4 and (not scope or r["scope"] in (scope, "")):
            scored.append((similarity, r))
    seen, out = set(), []
    for _, r in sorted(scored, key=lambda x: -x[0]):
        if normalize(r["question"]) in seen:
            continue
        seen.add(normalize(r["question"]))
        out.append({"question": r["question"], "plan": json.loads(r["plan"]),
                    "understanding": json.loads(r["result"]).get("understanding", "")})
        if len(out) >= limit:
            break
    return out
