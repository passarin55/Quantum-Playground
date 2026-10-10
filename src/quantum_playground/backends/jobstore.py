"""Persistent SQLite job store.

Unlike the reference v5–v8 Enigma tab (which could not decode a job from a
previous session), every submission stores the experiment id, parameters,
analysis context and register layout, so results fetched days later are
re-analysed exactly as if the session had never ended.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..config import qplay_home

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    backend     TEXT NOT NULL,
    experiment  TEXT,
    params      TEXT,
    context     TEXT,
    registers   TEXT,
    shots       INTEGER,
    status      TEXT,
    created_at  REAL,
    updated_at  REAL,
    results     TEXT,
    report      TEXT,
    preflight   TEXT,
    error       TEXT,
    extra       TEXT
);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC);
"""

_JSON_FIELDS = ("params", "context", "registers", "results", "report", "preflight", "extra")


class JobStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else qplay_home() / "jobs.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, job_id: str, provider: str, backend: str, *, experiment: Optional[str] = None,
            params: Any = None, context: Any = None, registers: Any = None, shots: Optional[int] = None,
            status: str = "QUEUED", preflight: Any = None, extra: Any = None) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO jobs (job_id, provider, backend, experiment, params, context, registers, "
                "shots, status, created_at, updated_at, preflight, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, provider, backend, experiment, _dump(params), _dump(context), _dump(registers), shots,
                 status, now, now, _dump(preflight), _dump(extra)))

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(_dump(v) if k in _JSON_FIELDS else v)
        cols.append("updated_at = ?")
        vals.append(time.time())
        vals.append(job_id)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id = ?", vals)

    def get(self, job_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row(row) if row else None

    def list(self, limit: int = 50, include_results: bool = False) -> list[dict]:
        cols = "*" if include_results else ("job_id, provider, backend, experiment, params, shots, status, "
                                            "created_at, updated_at, error")
        with self._conn() as c:
            rows = c.execute(f"SELECT {cols} FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]

    def delete(self, job_id: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,)).rowcount > 0


def _dump(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, default=str)


def _row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in _JSON_FIELDS:
        if k in d and d[k] is not None:
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
    return d
