import base64
import sqlite3
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from stock_crawler.job_store import JobStore, RateLimited


class WaitingExecutor:
    def submit(self, *args):
        pass


class InlineExecutor:
    def submit(self, function, *args):
        function(*args)


def test_render_blueprint_is_single_process_public_by_default_and_lax():
    blueprint = yaml.safe_load(Path("render.yaml").read_text())
    service = blueprint["services"][0]
    env = {item["key"]: item for item in service["envVars"]}
    assert service["type"] == "web" and service["runtime"] == "python"
    assert service["plan"] == "free" and "disk" not in service
    assert service["buildCommand"] == "uv sync --locked"
    assert "--host 0.0.0.0" in service["startCommand"]
    assert "--port $PORT" in service["startCommand"] and "--workers 1" in service["startCommand"]
    assert service["healthCheckPath"] == "/api/health"
    assert "STOCK_CRAWLER_AUTH_PASSWORD" not in env
    assert env["STOCK_CRAWLER_REPORT_WORKERS"]["value"] == "1"
    # Admission settings are omitted so Dashboard overrides survive Blueprint sync.
    assert "STOCK_CRAWLER_REPORTS_PER_HOUR" not in env


def test_cli_uses_render_port_but_localhost_by_default(monkeypatch):
    import uvicorn
    from stock_crawler.__main__ import main
    run_args = {}
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: run_args.update(target=target, **kwargs))
    assert main(["serve"]) == 0
    assert run_args["host"] == "127.0.0.1" and run_args["port"] == 12345
    assert main(["serve", "--host", "0.0.0.0", "--port", "8080"]) == 0
    assert run_args["host"] == "0.0.0.0" and run_args["port"] == 8080


def test_shared_password_protects_all_routes_except_health(tmp_path, monkeypatch):
    import stock_crawler.app as web
    manager = web.JobManager(tmp_path)
    manager.executor.shutdown()
    manager.executor = WaitingExecutor()
    monkeypatch.setattr(web, "manager", manager)
    monkeypatch.setenv("STOCK_CRAWLER_AUTH_USER", "researcher")
    monkeypatch.setenv("STOCK_CRAWLER_AUTH_PASSWORD", "a-strong-password")
    client = TestClient(web.app)
    assert client.get("/api/health").status_code == 200
    for path in ("/", "/api/config", "/static/app.js", "/docs"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic ")
        assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/reports", json={"ticker": "AAPL"}).status_code == 401
    assert client.get("/", auth=("researcher", "wrong")).status_code == 401
    assert client.get("/", auth=("wrong", "a-strong-password")).status_code == 401
    response = client.get("/", auth=("researcher", "a-strong-password"))
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "a-strong-password" not in response.text
    assert client.post("/api/reports", json={"ticker": "DEMO", "demo": True},
                       auth=("researcher", "a-strong-password")).status_code == 202
    monkeypatch.delenv("STOCK_CRAWLER_AUTH_PASSWORD")
    assert client.get("/").status_code == 200  # Local development remains available.


def test_lax_limit_only_counts_accepted_report_submissions(tmp_path, monkeypatch):
    import stock_crawler.app as web
    manager = web.JobManager(tmp_path, max_active=10, hourly_limit=2)
    manager.executor.shutdown()
    manager.executor = WaitingExecutor()
    monkeypatch.setattr(web, "manager", manager)
    monkeypatch.delenv("STOCK_CRAWLER_AUTH_PASSWORD", raising=False)
    client = TestClient(web.app)
    assert client.post("/api/reports", json={"ticker": "../bad"}).status_code == 422
    first = client.post("/api/reports", json={"ticker": "AAPL"})
    second = client.post("/api/reports", json={"ticker": "MSFT"})
    assert first.status_code == second.status_code == 202
    denied = client.post("/api/reports", json={"ticker": "GOOG"})
    assert denied.status_code == 429 and int(denied.headers["retry-after"]) > 0
    # Frequent progress polling, PDFs and health checks aren't rate-limited.
    assert all(client.get(first.json()["status_url"]).status_code == 200 for _ in range(8))
    assert client.get("/api/health").status_code == 200
    assert client.get(first.json()["status_url"] + "/pdf").status_code == 409


def test_limit_survives_reopen_and_can_be_disabled(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    first = store.create("AAPL", False, max_active=10, hourly_limit=1)
    reopened = JobStore(tmp_path)
    with pytest.raises(RateLimited) as error:
        reopened.create("MSFT", False, max_active=10, hourly_limit=1)
    assert 1 <= error.value.retry_after <= 3600
    assert reopened.create("MSFT", False, max_active=10, hourly_limit=0) != first
    now = time.time()
    monkeypatch.setattr("stock_crawler.job_store.time.time", lambda: now + 3601)
    assert reopened.create("GOOG", False, max_active=10, hourly_limit=1)


def test_completed_job_and_pdf_are_recoverable_after_restart(tmp_path, monkeypatch):
    import stock_crawler.app as web
    first = web.JobManager(tmp_path)
    first.executor.shutdown()
    first.executor = InlineExecutor()
    job_id = first.submit("DEMO", True)
    original = first.get(job_id)
    assert original["status"] == "complete"
    pdf = tmp_path / f"{job_id}.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    second = web.JobManager(tmp_path)
    monkeypatch.setattr(web, "manager", second)
    assert second.get(job_id) == original
    response = TestClient(web.app).get(f"/api/reports/{job_id}/pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    second.executor.shutdown(wait=True)


def test_interrupted_jobs_are_retried_from_scratch(tmp_path):
    import stock_crawler.app as web
    store = JobStore(tmp_path)
    running = store.create("DEMO", True, max_active=10, hourly_limit=0)
    queued = store.create("DEMO", True, max_active=10, hourly_limit=0)
    store.update(running, status="running", progress=78, stage="Writing")
    (tmp_path / f".{running}.tmp").write_text("interrupted")
    (tmp_path / f"{running}.pdf").write_text("incomplete")
    restarted = web.JobManager(tmp_path, max_workers=1)
    restarted.executor.shutdown(wait=True)
    for job_id in (running, queued):
        job = restarted.get(job_id)
        assert job["status"] == "complete"
        assert (tmp_path / f"{job_id}.pdf").read_bytes().startswith(b"%PDF")
        assert not (tmp_path / f".{job_id}.tmp").exists()


def test_old_jobs_and_pdfs_expire_but_scorecard_history_is_untouched(tmp_path):
    store = JobStore(tmp_path, retention_hours=1)
    job_id = store.create("AAPL", False, max_active=10, hourly_limit=0)
    store.update(job_id, status="complete", finished=time.time() - 3601,
                 result={"ticker": "AAPL", "price_date": "2025-01-01"})
    pdf = tmp_path / f"{job_id}.pdf"
    pdf.write_bytes(b"%PDF")
    archive = tmp_path / "scorecard-history.sqlite3"
    archive.write_text("keep")
    assert store.get(job_id) is None
    assert not pdf.exists()
    assert archive.read_text() == "keep"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_stale_unfinished_job_is_marked_failed_not_replayed(tmp_path):
    store = JobStore(tmp_path, retention_hours=1)
    job_id = store.create("AAPL", False, max_active=10, hourly_limit=0)
    store.update(job_id, status="running")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE jobs SET created = ? WHERE id = ?", (time.time() - 3601, job_id))
    temp = tmp_path / f".{job_id}.tmp"
    temp.write_text("old")
    assert store.recover() == []
    assert store.get(job_id)["status"] == "failed"
    assert "expired" in store.get(job_id)["error"]
    assert not temp.exists()


def test_concurrent_admission_does_not_exceed_the_hourly_limit(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = JobStore(tmp_path)
    def attempt(_):
        try:
            return store.create("AAPL", False, max_active=100, hourly_limit=10)
        except RateLimited:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = list(pool.map(attempt, range(30)))
    assert len([item for item in accepted if item]) == 10


def test_queue_rejection_does_not_use_an_hourly_slot(tmp_path):
    from stock_crawler.job_store import QueueFull
    store = JobStore(tmp_path)
    job = store.create("AAPL", False, max_active=1, hourly_limit=2)
    with pytest.raises(QueueFull):
        store.create("MSFT", False, max_active=1, hourly_limit=2)
    store.update(job, status="failed", finished=time.time(), result=None)
    assert store.create("GOOG", False, max_active=1, hourly_limit=2)
    with pytest.raises(RateLimited):
        store.create("NVDA", False, max_active=10, hourly_limit=2)


def test_invalid_auth_is_rejected_and_utf8_credentials_are_supported(monkeypatch):
    import stock_crawler.app as web
    monkeypatch.setenv("STOCK_CRAWLER_AUTH_USER", "analyst")
    monkeypatch.setenv("STOCK_CRAWLER_AUTH_PASSWORD", "a:strong:password")
    client = TestClient(web.app)
    assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.get("/", headers={"Authorization": "Bearer token"}).status_code == 401
    assert client.get("/", auth=("analyst", "a:strong:password")).status_code == 200
    encoded = base64.b64encode("研究员:päss:秘密".encode()).decode()
    assert web._authorized("Basic " + encoded, "研究员", "päss:秘密")


def test_storage_failure_returns_503_instead_of_crashing(tmp_path, monkeypatch):
    import stock_crawler.app as web
    manager = web.JobManager(tmp_path)
    manager.executor.shutdown()
    monkeypatch.setattr(web, "manager", manager)
    monkeypatch.delenv("STOCK_CRAWLER_AUTH_PASSWORD", raising=False)
    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("sensitive path should not be returned")
    monkeypatch.setattr(manager.store, "create", fail)
    response = TestClient(web.app).post("/api/reports", json={"ticker": "AAPL"})
    assert response.status_code == 503
    assert "sensitive path" not in response.text


def test_hosting_configuration_accepts_zero_limit_and_rejects_bad_values(tmp_path, monkeypatch):
    import stock_crawler.app as web
    monkeypatch.delenv("STOCK_CRAWLER_REPORTS_PER_HOUR", raising=False)
    defaults = web.JobManager(tmp_path / "defaults")
    assert defaults.hourly_limit == 240
    defaults.executor.shutdown()
    monkeypatch.setenv("STOCK_CRAWLER_REPORTS_PER_HOUR", "0")
    monkeypatch.setenv("STOCK_CRAWLER_MAX_ACTIVE_REPORTS", "bad")
    monkeypatch.setenv("STOCK_CRAWLER_JOB_RETENTION_HOURS", "0")
    manager = web.JobManager(tmp_path)
    assert manager.hourly_limit == 0 and manager.max_active == 12
    assert manager.store.retention_seconds == 168 * 3600
    manager.executor.shutdown()


def test_worker_storage_failure_is_retried_and_queue_slot_is_released(tmp_path, monkeypatch):
    import stock_crawler.app as web
    manager = web.JobManager(tmp_path, max_active=1)
    manager.executor.shutdown()
    manager.executor = InlineExecutor()
    real_update = manager.store.update
    failures = [True, True, True]
    def flaky_update(*args, **kwargs):
        if failures:
            failures.pop()
            raise sqlite3.OperationalError("temporarily read-only")
        return real_update(*args, **kwargs)
    monkeypatch.setattr(manager.store, "update", flaky_update)
    job_id = manager.submit("DEMO", True)
    # First write and failed-state write fail; the next health flush also fails.
    assert not manager.healthy()
    # Once storage is writable, polling persists the failure and frees the slot.
    assert manager.get(job_id)["status"] == "failed"
    assert manager.healthy()
    next_job = manager.submit("DEMO", True)
    assert manager.get(next_job)["status"] == "complete"
