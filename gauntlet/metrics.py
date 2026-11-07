"""Deterministic scoring + metrics persistence.

MVP scoring needs no LLM judge: each task carries a `check` that is evaluated
against the agent's final answer. Results are written as JSON Lines (one object
per run) and mirrored into SQLite for the dashboard.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from .base import AgentResult, Task

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
JSONL_PATH = RESULTS_DIR / "runs.jsonl"
SQLITE_PATH = RESULTS_DIR / "gauntlet.sqlite"


# ── Scoring ────────────────────────────────────────────────────────────────────
def _extract_number(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


def _word_present(value: str, text: str) -> bool:
    """Case-insensitive match of `value` in `text` with word boundaries, so short
    tokens like 'Go' don't spuriously match inside 'Google'. Works for values
    containing non-word chars (e.g. emails) because the lookarounds only forbid
    an adjacent word char."""
    pattern = r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def score(task: Task, answer: str) -> bool:
    """Return True iff `answer` satisfies the task's deterministic check."""
    if answer is None:
        return False
    chk = task.check
    ctype = chk.get("type")
    val = chk.get("value")
    ans = answer.strip()
    low = ans.lower()

    if ctype == "numeric_equals":
        got = _extract_number(ans)
        if got is None:
            return False
        return abs(got - float(val)) < 1e-6

    if ctype == "contains_any":
        return any(_word_present(str(v), ans) for v in val)

    if ctype == "contains_all":
        return all(_word_present(str(v), ans) for v in val)

    if ctype == "regex":
        return re.search(val, ans) is not None

    raise ValueError(f"unknown check type: {ctype!r}")


# ── Persistence ────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT,
    agent             TEXT,
    task_id           TEXT,
    chaos_mode        TEXT,
    success           INTEGER,
    final_answer      TEXT,
    steps             INTEGER,
    tool_calls        INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    cost_usd          REAL,
    latency_ms        REAL,
    retries           INTEGER,
    error             TEXT
);
"""


def _connect() -> sqlite3.Connection:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute(_SCHEMA)
    return conn


def write_results(results: Iterable[AgentResult]) -> int:
    """Append results to JSONL and SQLite. Returns count written."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results = list(results)
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        for r in results:
            rec = r.flat_row()
            rec["trace"] = r.trace
            f.write(json.dumps(rec) + "\n")

    conn = _connect()
    cols = [
        "run_id", "agent", "task_id", "chaos_mode", "success", "final_answer",
        "steps", "tool_calls", "prompt_tokens", "completion_tokens",
        "total_tokens", "cost_usd", "latency_ms", "retries", "error",
    ]
    placeholders = ",".join("?" * len(cols))
    with conn:
        for r in results:
            row = r.flat_row()
            row["success"] = int(row["success"])
            conn.execute(
                f"INSERT INTO runs ({','.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
    conn.close()
    return len(results)


def load_rows() -> list[dict]:
    """Read all rows from SQLite for the dashboard."""
    if not SQLITE_PATH.exists():
        return []
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM runs")]
    conn.close()
    return rows
