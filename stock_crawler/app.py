"""Local, single-process web application and asynchronous report jobs."""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stock_crawler import __version__
from stock_crawler.analysis import analyze
from stock_crawler.archive import record_signal
from stock_crawler.collector import collect
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


class JobManager:
    def __init__(self, output_dir: Path, max_workers: int = 2, max_active: int = 6):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_active = max_active
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="report")
        self.jobs: dict[str, dict[str, Any]] = {}

    def submit(self, ticker: str, demo: bool) -> str:
        job_id = str(uuid.uuid4())
        with self.lock:
            now = time.time()
            # Keep completed status in memory for 24 hours. PDF files remain on
            # disk until the user deletes them; a restart also clears job status.
            for key in list(self.jobs):
                job = self.jobs[key]
                if job["status"] in {"complete", "failed"} and now - job.get("finished", job["created"]) > 86_400:
                    del self.jobs[key]
            if sum(j["status"] in {"queued", "running"} for j in self.jobs.values()) >= self.max_active:
                raise RuntimeError("The research queue is full. Please try again in a moment.")
            self.jobs[job_id] = {
                "id": job_id, "ticker": "DEMO" if demo else ticker, "demo": demo,
                "status": "queued", "progress": 0, "stage": "Waiting for a research slot",
                "created": now, "result": None, "error": None,
            }
        self.executor.submit(self._run, job_id, ticker, demo)
        return job_id

    def _update(self, job_id: str, **changes: Any) -> None:
        if changes.get("status") in {"complete", "failed"}:
            changes["finished"] = time.time()
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(changes)

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
            self._update(job_id, status="failed", stage="Research could not be completed", error=str(exc))
        except Exception:
            log.exception("Report job %s failed", job_id)
            self._update(job_id, status="failed", stage="Research could not be completed",
                         error="Something went wrong while building the report. Check the server logs and try again.")
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job["status"] in {"complete", "failed"} and time.time() - job.get("finished", job["created"]) > 86_400:
                del self.jobs[job_id]
                return None
            # Do not return internal timestamps or mutable references.
            return {key: (dict(value) if isinstance(value, dict) else value) for key, value in job.items() if key not in {"created", "finished"}}


app = FastAPI(title="Stock Crawler", version=__version__)
manager = JobManager(REPORT_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/config")
def config():
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    return {"version": __version__, "sec_enabled": bool(agent and _valid_agent(agent))}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/reports", status_code=202)
def start_report(request: ReportRequest):
    try:
        ticker = normalize_ticker(request.ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        job_id = manager.submit(ticker, request.demo)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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
