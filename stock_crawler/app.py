"""Single-process research app with restart-safe, disk-backed report jobs."""
from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stock_crawler import __version__
from stock_crawler.analysis import analyze
from stock_crawler.archive import record_signal
from stock_crawler.collector import collect
from stock_crawler.job_store import JobStore, QueueFull, RateLimited
from stock_crawler.report import create_report
from stock_crawler.sources.market import MarketDataError
from stock_crawler.sources.sec import _valid_agent
from stock_crawler.utils import normalize_ticker

log = logging.getLogger("stock_crawler")
STATIC_DIR = Path(__file__).parent / "static"
REPORT_DIR = Path(os.getenv("STOCK_CRAWLER_REPORT_DIR", "reports")).expanduser().resolve()


class ReportRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=40)
    demo: bool = False


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        if minimum <= value <= maximum:
            return value
    except ValueError:
        pass
    log.warning("Invalid %s; using default %s", name, default)
    return default


def _authorized(header: str, expected_user: str, expected_password: str) -> bool:
    if len(header) > 4096:
        return False
    scheme, separator, encoded = header.partition(" ")
    if not separator or scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    user, separator, password = decoded.partition(":")
    if not separator:
        return False
    # Evaluate both comparisons and use byte strings, which also supports
    # non-ASCII credentials without compare_digest raising a TypeError.
    user_matches = hmac.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
    password_matches = hmac.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8"))
    return user_matches and password_matches


class JobManager:
    def __init__(self, output_dir: Path, max_workers: int | None = None, max_active: int | None = None,
                 hourly_limit: int | None = None, retention_hours: int | None = None):
        self.output_dir = output_dir
        max_workers = max_workers if max_workers is not None else _env_int("STOCK_CRAWLER_REPORT_WORKERS", 2, 1, 8)
        self.max_active = max_active if max_active is not None else _env_int("STOCK_CRAWLER_MAX_ACTIVE_REPORTS", 12, 1, 100)
        self.hourly_limit = hourly_limit if hourly_limit is not None else _env_int("STOCK_CRAWLER_REPORTS_PER_HOUR", 240, 0, 1000000)
        retention_hours = retention_hours if retention_hours is not None else _env_int("STOCK_CRAWLER_JOB_RETENTION_HOURS", 168, 1, 8760)
        self.store = JobStore(output_dir, retention_hours)
        # If a write fails while a worker is handling an error, retry recording
        # the terminal state on the next request rather than leaving a ghost job.
        self.pending_failures: dict[str, dict[str, Any]] = {}
        self.pending_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="report")
        # Only one process/instance may own this directory. On startup, rerun
        # unfinished work; completed jobs and links survive on a persistent disk.
        for job_id, ticker, demo in self.store.recover():
            self.executor.submit(self._run, job_id, ticker, demo)

    def submit(self, ticker: str, demo: bool) -> str:
        self.flush_failures()
        job_id = self.store.create(ticker, demo, self.max_active, self.hourly_limit)
        try:
            self.executor.submit(self._run, job_id, ticker, demo)
        except RuntimeError:
            self._fail(job_id, "The research service is restarting. Please try again.")
            raise
        return job_id

    def _update(self, job_id: str, **changes: Any) -> None:
        if changes.get("status") in {"complete", "failed"}:
            changes["finished"] = time.time()
        self.store.update(job_id, **changes)

    def _fail(self, job_id: str, message: str) -> None:
        changes = {"status": "failed", "stage": "Research could not be completed", "error": message}
        try:
            self._update(job_id, **changes)
        except (sqlite3.Error, OSError):
            log.exception("Could not persist failed state for report %s; it will be retried", job_id)
            with self.pending_lock:
                self.pending_failures[job_id] = changes

    def flush_failures(self) -> None:
        with self.pending_lock:
            for job_id, changes in list(self.pending_failures.items()):
                self._update(job_id, **changes)
                del self.pending_failures[job_id]

    def _run(self, job_id: str, ticker: str, demo: bool) -> None:
        temporary = self.output_dir / f".{job_id}.tmp"
        destination = self.output_dir / f"{job_id}.pdf"
        try:
            self._update(job_id, status="running", progress=3, stage="Starting research")
            snapshot = collect(ticker, demo=demo, progress=lambda p, stage: self._update(job_id, progress=p, stage=stage))
            analysis = analyze(snapshot)
            self._update(job_id, progress=78, stage="Connecting the thesis, historical test and price ranges")
            pages = create_report(snapshot, analysis, temporary)
            self._update(job_id, progress=96, stage="Finalizing your PDF")
            os.replace(temporary, destination)
            analysis.limitations.extend(record_signal(snapshot, analysis))
            result = {
                "ticker": snapshot.ticker, "company": snapshot.name, "currency": snapshot.currency,
                "verdict": analysis.verdict, "score": analysis.score, "coverage": analysis.coverage,
                "last_close": snapshot.price, "price_date": snapshot.price_date.isoformat(),
                "ranges": [{"months": item.months, "end_date": item.end_date.isoformat(), "low": item.low, "high": item.high}
                           for item in analysis.ranges],
                "backtest": ({"method": analysis.backtest.method,
                              "horizons": [{"months": item.months, "calls": item.directional_calls,
                                            "hits": item.correct_calls, "hit_rate": item.hit_rate,
                                            "always_up_rate": item.always_up_rate}
                                           for item in analysis.backtest.horizons]} if analysis.backtest else None),
                "recorded_backtest": ({"method": analysis.recorded_backtest.method,
                                       "horizons": [{"months": item.months, "calls": item.directional_calls,
                                                     "hits": item.correct_calls, "hit_rate": item.hit_rate,
                                                     "always_up_rate": item.always_up_rate}
                                                    for item in analysis.recorded_backtest.horizons]}
                                      if analysis.recorded_backtest else None),
                "pages": pages,
                "warnings": analysis.limitations, "demo": snapshot.demo,
                "pdf_url": f"/api/reports/{job_id}/pdf",
            }
            self._update(job_id, status="complete", progress=100, stage="Research complete", result=result)
        except MarketDataError as exc:
            self._fail(job_id, str(exc))
        except Exception:
            log.exception("Report job %s failed", job_id)
            self._fail(job_id, "Something went wrong while building the report. Check the server logs and try again.")
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove temporary file for report %s", job_id, exc_info=True)

    def get(self, job_id: str) -> dict[str, Any] | None:
        self.flush_failures()
        return self.store.get(job_id)

    def healthy(self) -> bool:
        try:
            self.flush_failures()
            return self.store.healthy()
        except (sqlite3.Error, OSError):
            return False


app = FastAPI(title="Stock Crawler", version=__version__)
manager = JobManager(REPORT_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def shared_password_and_headers(request: Request, call_next):
    # A shared password is optional. Local development and the default Render
    # Blueprint remain open; Render health checks must always be reachable.
    password = os.getenv("STOCK_CRAWLER_AUTH_PASSWORD", "")
    user = os.getenv("STOCK_CRAWLER_AUTH_USER", "researcher")
    if password and request.url.path != "/api/health" and not _authorized(request.headers.get("authorization", ""), user, password):
        return JSONResponse({"detail": "Authentication required."}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Stock Crawler", charset="UTF-8"',
                                     "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(OSError)
@app.exception_handler(sqlite3.Error)
async def storage_error_handler(request: Request, exc: sqlite3.Error | OSError):
    log.error("Report job storage failed: %s", type(exc).__name__)
    return JSONResponse({"detail": "Report storage is unavailable; please try again later."}, status_code=503,
                        headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def config():
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    return {"version": __version__, "sec_enabled": bool(agent and _valid_agent(agent))}


@app.get("/api/health")
def health():
    if not manager.healthy():
        raise HTTPException(status_code=503, detail="Report storage is unavailable.")
    return {"status": "ok"}


@app.post("/api/reports", status_code=202)
def start_report(request: ReportRequest):
    try:
        ticker = normalize_ticker(request.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        job_id = manager.submit(ticker, request.demo)
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
    except QueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "10"}) from exc
    except RuntimeError as exc:
        log.exception("Could not start report job")
        raise HTTPException(status_code=503, detail="The research service is restarting. Please try again.") from exc
    return {"id": job_id, "status_url": f"/api/reports/{job_id}"}


@app.get("/api/reports/{job_id}")
def report_status(job_id: uuid.UUID):
    result = manager.get(str(job_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Report job not found or expired.")
    return result


@app.get("/api/reports/{job_id}/pdf")
def report_pdf(job_id: uuid.UUID, download: bool = False):
    job = manager.get(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found or expired.")
    if job["status"] != "complete":
        raise HTTPException(status_code=409, detail="The PDF is not ready yet.")
    result = job["result"]
    file = manager.output_dir / f"{job_id}.pdf"
    if not file.is_file():
        raise HTTPException(status_code=404, detail="The PDF file is no longer available.")
    return FileResponse(file, media_type="application/pdf", filename=f"{result['ticker']}-stock-crawler-{result['price_date']}.pdf",
                        content_disposition_type="attachment" if download else "inline", headers={"Cache-Control": "no-store"})
