"""Local, append-only-by-day scorecard archive for genuine prospective tests.

No demo reports or incomplete verdicts are recorded. A recorded verdict is
frozen at report time and is never backfilled with today's fundamentals.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stock_crawler.models import Analysis, RecordedSignal, Snapshot

# Bump this identifier whenever verdict, weighting, gates, or factor rules change.
# Old records must not be silently mixed with a different scorecard.
MODEL_REVISION = "scorecard-1.1.0"


def archive_path() -> Path:
    configured = os.getenv("STOCK_CRAWLER_HISTORY_DB", "").strip()
    return Path(configured).expanduser() if configured else Path(os.getenv("STOCK_CRAWLER_REPORT_DIR", "reports")) / "scorecard-history.sqlite3"


def load_signals(ticker: str, path: Path | None = None) -> tuple[list[RecordedSignal], list[str]]:
    path = path or archive_path()
    if not path.is_file():
        return [], []
    try:
        # Read-only opening avoids creating an empty archive during collection.
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
            rows = connection.execute(
                "SELECT observed_at, score, verdict FROM signals WHERE ticker = ? AND model_revision = ? ORDER BY observed_at",
                (ticker.upper(), MODEL_REVISION),
            ).fetchall()
        result = []
        for raw_time, score, verdict in rows:
            observed = datetime.fromisoformat(raw_time)
            if observed.tzinfo is None:
                continue
            if (verdict in {"Bullish", "Bearish", "Mixed / neutral"} and isinstance(score, (int, float))
                    and math.isfinite(score) and -1 <= score <= 1):
                result.append(RecordedSignal(observed.astimezone(timezone.utc), float(score), verdict))
        return result, []
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return [], ["The local scorecard archive could not be read; full-scorecard prospective results are unavailable."]


def record_signal(snapshot: Snapshot, analysis: Analysis, path: Path | None = None,
                  observed_at: datetime | None = None) -> list[str]:
    if snapshot.demo or analysis.score is None or analysis.verdict not in {"Bullish", "Bearish", "Mixed / neutral"}:
        return []
    path = path or archive_path()
    observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    factors = [{"key": f.key, "weight": f.weight, "score": f.score} for f in analysis.factors]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS signals (
                ticker TEXT NOT NULL, model_revision TEXT NOT NULL, signal_day TEXT NOT NULL,
                observed_at TEXT NOT NULL, quote_date TEXT NOT NULL, score REAL NOT NULL,
                coverage REAL NOT NULL, verdict TEXT NOT NULL, factors_json TEXT NOT NULL,
                PRIMARY KEY (ticker, model_revision, signal_day)
            )""")
            # The first report per ticker/UTC day is retained, preventing
            # subsequent runs from retroactively replacing an earlier signal.
            connection.execute("""INSERT OR IGNORE INTO signals
                (ticker, model_revision, signal_day, observed_at, quote_date, score, coverage, verdict, factors_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot.ticker.upper(), MODEL_REVISION, observed.date().isoformat(), observed.isoformat(),
                 snapshot.price_date.isoformat(), analysis.score, analysis.coverage, analysis.verdict,
                 json.dumps(factors, separators=(",", ":"), allow_nan=False)))
        return []
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return ["The local scorecard archive could not be written; this verdict will not be available for prospective evaluation."]
