"""Single-instance SQLite job storage for small hosted deployments.

The database and PDFs share one directory. A persistent disk preserves completed
jobs and permits unfinished jobs to be retried after a process restart. This is
not a distributed queue: only one app process may own a job directory.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("stock_crawler")
TERMINAL = ("complete", "failed")


class QueueFull(RuntimeError):
    pass


class RateLimited(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("The service has reached its hourly report limit. Please try again later.")
        self.retry_after = retry_after


class JobStore:
    def __init__(self, output_dir: Path, retention_hours: int = 168):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.output_dir / "report-jobs.sqlite3"
        self.retention_seconds = max(1, retention_hours) * 3600
        self.lock = threading.RLock()
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, ticker TEXT NOT NULL, demo INTEGER NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL, stage TEXT NOT NULL,
                created REAL NOT NULL, finished REAL, result_json TEXT, error TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status)")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created)")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _remove_files(self, job_ids: list[str]) -> None:
        for value in job_ids:
            try:
                # Never turn an unexpected database value into an arbitrary path.
                job_id = str(uuid.UUID(value))
                for file in (self.output_dir / f"{job_id}.pdf", self.output_dir / f".{job_id}.tmp"):
                    file.unlink(missing_ok=True)
            except (ValueError, OSError):
                log.warning("Could not remove expired report files for job %s", value)

    def _prune(self, db: sqlite3.Connection, now: float) -> list[str]:
        rows = db.execute("SELECT id FROM jobs WHERE status IN (?, ?) AND finished < ?",
                          (*TERMINAL, now - self.retention_seconds)).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            db.executemany("DELETE FROM jobs WHERE id = ?", ((value,) for value in ids))
        return ids

    def prune(self) -> None:
        with self.lock:
            with self._connection() as db:
                ids = self._prune(db, time.time())
            self._remove_files(ids)

    def create(self, ticker: str, demo: bool, max_active: int, hourly_limit: int) -> str:
        now = time.time()
        with self.lock:
            # On this single-process deployment the lock makes the active-job
            # and hourly checks atomic with insertion.
            with self._connection() as db:
                expired = self._prune(db, now)
                active = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
                if active >= max_active:
                    raise QueueFull("The research queue is full. Please try again in a moment.")
                if hourly_limit > 0:
                    count, first = db.execute("SELECT COUNT(*), MIN(created) FROM jobs WHERE created > ?",
                                              (now - 3600,)).fetchone()
                    if count >= hourly_limit:
                        raise RateLimited(max(1, math.ceil(first + 3600 - now)))
                job_id = str(uuid.uuid4())
                db.execute("""INSERT INTO jobs
                    (id, ticker, demo, status, progress, stage, created)
                    VALUES (?, ?, ?, 'queued', 0, 'Waiting for a research slot', ?)""",
                    (job_id, "DEMO" if demo else ticker, int(demo), now))
            self._remove_files(expired)
            return job_id

    def update(self, job_id: str, **changes: Any) -> None:
        allowed = {"status", "progress", "stage", "finished", "result", "error"}
        if not set(changes).issubset(allowed):
            raise ValueError("Unexpected job field")
        if not changes:
            return
        values = dict(changes)
        if "result" in values:
            result = values.pop("result")
            values["result_json"] = json.dumps(result, allow_nan=False) if result is not None else None
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.lock, self._connection() as db:
            db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))

    def get(self, job_id: str) -> dict[str, Any] | None:
        expired: list[str] = []
        with self.lock:
            with self._connection() as db:
                row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if row and row["finished"] is not None and row["finished"] < time.time() - self.retention_seconds:
                    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                    expired.append(job_id)
                    row = None
            self._remove_files(expired)
            if row is None:
                return None
            return {
                "id": row["id"], "ticker": row["ticker"], "demo": bool(row["demo"]),
                "status": row["status"], "progress": row["progress"], "stage": row["stage"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "error": row["error"],
            }

    def recover(self) -> list[tuple[str, str, bool]]:
        """Requeue recent unfinished jobs once after the previous process exits."""
        now = time.time()
        with self.lock:
            with self._connection() as db:
                expired = self._prune(db, now)
                stale = [row["id"] for row in db.execute(
                    "SELECT id FROM jobs WHERE status IN ('queued', 'running') AND created < ?",
                    (now - self.retention_seconds,),
                ).fetchall()]
                db.execute("""UPDATE jobs SET status='failed', finished=?, stage='Research interrupted',
                    error='This unfinished report expired while the service was offline. Please start it again.'
                    WHERE status IN ('queued', 'running') AND created < ?""", (now, now - self.retention_seconds))
                db.execute("""UPDATE jobs SET status='queued', progress=0,
                    stage='Resuming research after a service restart', finished=NULL, result_json=NULL, error=NULL
                    WHERE status IN ('queued', 'running')""")
                rows = db.execute("SELECT id, ticker, demo FROM jobs WHERE status = 'queued' ORDER BY created").fetchall()
            self._remove_files(expired + stale + [row["id"] for row in rows])
            return [(row["id"], row["ticker"], bool(row["demo"])) for row in rows]

    def healthy(self) -> bool:
        try:
            with self._connection() as db:
                db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone()
            return True
        except sqlite3.Error:
            log.exception("Report job storage is unavailable")
            return False
