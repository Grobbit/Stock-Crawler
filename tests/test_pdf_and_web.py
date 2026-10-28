from dataclasses import replace

from fastapi.testclient import TestClient
from pypdf import PdfReader

from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.report import create_report
from stock_crawler.models import NewsItem


def test_demo_pdf_has_structured_sections_disclosures_and_calculation(tmp_path):
    snapshot = demo_snapshot()
    analysis = analyze(snapshot)
    path = tmp_path / "demo.pdf"
    pages = create_report(snapshot, analysis, path)
    reader = PdfReader(path)
    assert 10 <= pages == len(reader.pages) <= 30
    content = "\n".join(page.extract_text() for page in reader.pages)
    for expected in ["SYNTHETIC DEMO", "Northstar Analytics", "The investment decision", "The bull case", "The bear case",
                     "Management & stewardship", "The business & its customers", "macro reaches this stock",
                     "Annual income statement history", "Annual cash-flow history", "News tone & sentiment trends",
                     "Market positioning & risk", "Elections & elected officials", "Policy exposure & the company",
                     "Stock reactions around elections", "Model rules & limitations", "Sources & data gaps", "fictional"]:
        assert expected in content
    assert "USD " + f"{analysis.target:,.2f}" in content


def test_pdf_is_honest_with_missing_or_inapplicable_data(tmp_path):
    snapshot = demo_snapshot()
    snapshot.demo = False
    snapshot.info["quoteType"] = "ETF"
    snapshot.info["longBusinessSummary"] = None
    snapshot.info["companyOfficers"] = []
    snapshot.info["currency"] = "GBp"
    snapshot.info["financialCurrency"] = "GBP"
    snapshot.filing = None
    snapshot.macro = {}
    snapshot.annuals = []
    snapshot.news = []
    analysis = analyze(snapshot)
    path = tmp_path / "limited.pdf"
    pages = create_report(snapshot, analysis, path)
    assert 10 <= pages <= 30
    import re
    content = re.sub(r"\s+", " ", " ".join(p.extract_text() for p in PdfReader(path).pages)).lower()
    assert "insufficient evidence" in content
    assert "no six-month price target is issued" in content
    assert "do not establish named customers" in content
    assert "not supply officer names" in content
    assert "ratios are withheld" in content


def test_long_external_fields_do_not_break_page_range(tmp_path):
    snapshot = demo_snapshot()
    snapshot.info["longBusinessSummary"] = "Long company disclosure sentence with useful details. " * 200
    snapshot.info["companyOfficers"] = [{"name": "A" * 100, "title": "C" * 200} for _ in range(12)]
    day = snapshot.fetched_at.date().isoformat()
    snapshot.news = [NewsItem(f"Northstar headline {i} " + "detailed description " * 7, "Publisher", day,
                              f"https://example.com/news/{i}") for i in range(20)]
    assert 10 <= create_report(snapshot, analyze(snapshot), tmp_path / "long.pdf") <= 30


class InlineExecutor:
    def submit(self, function, *args):
        function(*args)


def test_api_demo_job_and_pdf_download(tmp_path, monkeypatch):
    import stock_crawler.app as web
    local_manager = web.JobManager(tmp_path)
    local_manager.executor.shutdown()
    local_manager.executor = InlineExecutor()
    monkeypatch.setattr(web, "manager", local_manager)
    client = TestClient(web.app)
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.post("/api/reports", json={"ticker": "DEMO", "demo": True})
    assert response.status_code == 202
    status = client.get(response.json()["status_url"]).json()
    assert status["status"] == "complete"
    assert status["result"]["demo"]
    assert status["result"]["pages"] >= 10
    pdf = client.get(status["result"]["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert "inline" in pdf.headers["content-disposition"]
    downloaded = client.get(status["result"]["pdf_url"] + "?download=true")
    assert "attachment" in downloaded.headers["content-disposition"]
    assert client.post("/api/reports", json={"ticker": "../bad", "demo": False}).status_code == 422
    assert client.get("/api/reports/not-a-uuid").status_code == 422


def test_queue_limit_is_enforced_without_starting_extra_work(tmp_path):
    from stock_crawler.app import JobManager
    manager = JobManager(tmp_path, max_active=1)
    manager.executor.shutdown()
    class WaitingExecutor:
        def submit(self, *args): pass
    manager.executor = WaitingExecutor()
    manager.submit("AAPL", False)
    import pytest
    with pytest.raises(RuntimeError, match="queue is full"):
        manager.submit("MSFT", False)


def test_live_shaped_pdf_keeps_sources_and_caveats(tmp_path):
    snapshot = demo_snapshot()
    snapshot.demo = False
    snapshot.ticker = "TEST"
    snapshot.name = "Test Company"
    snapshot.filing = replace(snapshot.filing, url="https://www.sec.gov/Archives/example.html")
    snapshot.macro = {key: replace(point, source_url=f"https://fred.stlouisfed.org/series/{key}") for key, point in snapshot.macro.items()}
    snapshot.politics.source_url = "https://github.com/unitedstates/congress-legislators"
    snapshot.news = [NewsItem("Test Company wins a contract", "Example News", snapshot.fetched_at.date().isoformat(), "https://example.com/news")]
    path = tmp_path / "live-shaped.pdf"
    pages = create_report(snapshot, analyze(snapshot), path)
    assert 10 <= pages <= 30
    reader = PdfReader(path)
    content = "\n".join(p.extract_text() for p in reader.pages)
    for source in ("[Q]", "[H]", "[A]", "[S]", "[F]", "[M1]", "[M6]", "[M7]", "[M10]", "[N]", "[P]", "[E]", "[V]", "[O]", "[B]"):
        assert source in content
    links = []
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A", {})
            if "/URI" in action:
                links.append(str(action["/URI"]))
    assert "https://example.com/news" in links
    assert "https://github.com/unitedstates/congress-legislators" in links
    assert "https://fred.stlouisfed.org/series/GDPC1" in links


def test_command_line_demo_creates_pdf(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "cli.pdf"
    result = subprocess.run([sys.executable, "-m", "stock_crawler", "report", "--demo", "--output", str(path)],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert path.read_bytes().startswith(b"%PDF")
    assert "DEMO ONLY" in result.stderr
