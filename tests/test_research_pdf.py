from dataclasses import replace
from datetime import timedelta

from pypdf import PdfReader

from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot
from stock_crawler.models import (
    FilingEvent,
    NewsItem,
    PeerGroup,
    PeerValuation,
    RevenueBreakdown,
    RevenueComponent,
    WebResult,
)
from stock_crawler.report import create_report


def _live_shaped_snapshot():
    snapshot = demo_snapshot()
    snapshot.demo = False  # Synthetic data, but exercise live source-link rendering.
    snapshot.ticker = "TEST"
    snapshot.company_profile = replace(snapshot.company_profile, entity_id="Q123")
    filing = snapshot.filing
    quarter = replace(filing, form="10-Q", url="https://www.sec.gov/Archives/quarter.htm", latest_quarter=None)
    snapshot.filing = replace(filing, form="10-K", url="https://www.sec.gov/Archives/annual.htm", latest_quarter=quarter,
                              companyfacts_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000123.json",
                              sec_annuals=tuple(replace(row, source="SEC XBRL", currency="USD") for row in snapshot.annuals),
                              sec_quarters=tuple(replace(row, source="SEC XBRL", currency="USD") for row in snapshot.quarters),
                              recent_events=(FilingEvent("8-K", filing.filing_date, filing.report_date, "https://www.sec.gov/Archives/event.htm", ("2.02",)),))
    snapshot.web_news = [NewsItem("Northstar sales growth", "Example news", snapshot.fetched_at.date().isoformat(),
                                  "https://publisher.example.com/northstar", "en")]
    snapshot.web_results = [WebResult("Northstar contracts", "https://example.com/contracts", "A sample search snippet", "example.com",
                                      "2025-01-01", "Customers & products", "Brave Search")]
    snapshot.web_search_enabled = True
    return snapshot


def test_live_shaped_report_cites_specific_sources_and_marks_search_unverified(tmp_path):
    snapshot = _live_shaped_snapshot()
    path = tmp_path / "report.pdf"
    count = create_report(snapshot, analyze(snapshot), path)
    reader = PdfReader(path)
    content = " ".join(" ".join(page.extract_text().split()) for page in reader.pages)
    assert 10 <= count == len(reader.pages) <= 30
    for marker in ("[FQ]", "[X]", "[G]", "[W]", "[K]"):
        assert marker in content
    for phrase in ("Growth versus profitability", "Revenue drivers & issuer evidence", "Financial trajectory & quality",
                   "Independent leads & filing events", "research leads, not established company facts", "may be incomplete or outdated",
                   "reconciliation does not prove the categories are non-overlapping", "YoY change", "largest absolute change"):
        assert phrase in content
    links = []
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A", {})
            if "/URI" in action:
                links.append(str(action["/URI"]))
    for url in ("https://www.sec.gov/Archives/annual.htm", "https://www.sec.gov/Archives/quarter.htm",
                "https://publisher.example.com/northstar", "https://www.gdeltproject.org/", "https://example.com/contracts", "https://www.wikidata.org/wiki/Q123"):
        assert url in links


def test_deep_research_stress_report_stays_within_page_limit_without_orphans(tmp_path):
    snapshot = _live_shaped_snapshot()
    snapshot.name = "Long International Company Name " * 3
    snapshot.info["longBusinessSummary"] = "A detailed business summary of products and customers. " * 200
    snapshot.info["companyOfficers"] = [{"name": "Long Officer Name " * 4, "title": "Chief executive role " * 5} for _ in range(10)]
    today = snapshot.fetched_at.date().isoformat()
    snapshot.news = [NewsItem("Northstar company headline " + str(i) + " involving sales and growth " * 3,
                              "International Reporting Organization", today, "https://example.com/news/" + str(i)) for i in range(20)]
    snapshot.web_news = [NewsItem("Northstar independent headline " + str(i) + " about products and customers " * 3,
                                  "International Reporting Organization", today, "https://publisher.example.com/news/" + str(i)) for i in range(18)]
    snapshot.web_results = [WebResult("Northstar web result " + str(i) + " about company products and finances",
                                      "https://example.com/search/" + str(i), "Long search summary about the company and its competitors " * 3,
                                      "example.com", "2025-01-01", "Customers" if i < 5 else "Risks", "Brave Search") for i in range(10)]
    components = tuple(RevenueComponent("A very long detailed financial category " + str(i), 100_000_000,
                                        "corp:Label" + str(i) + "Member", 80_000_000) for i in range(10))
    mix = RevenueBreakdown("Products and services", snapshot.filing.report_date - timedelta(days=364), snapshot.filing.report_date,
                           "USD", 1_000_000_000, components, "us-gaap:Revenues", snapshot.filing.report_date - timedelta(days=729),
                           snapshot.filing.report_date - timedelta(days=365), 800_000_000)
    events = tuple(FilingEvent("8-K", snapshot.filing.filing_date, snapshot.filing.report_date,
                               "https://www.sec.gov/Archives/event.htm", ("1.01", "2.01", "2.02", "5.02")) for _ in range(6))
    snapshot.filing = replace(snapshot.filing, revenue_breakdowns=(mix, replace(mix, kind="Reported business segments")), recent_events=events)
    snapshot.peers = PeerGroup("example", "Software - Infrastructure", tuple(
        PeerValuation("P" + str(i), "Long company name for illustration " + str(i), "Software - Infrastructure", 20 + i, .15, .2)
        for i in range(8)), snapshot.fetched_at)
    path = tmp_path / "stress.pdf"
    count = create_report(snapshot, analyze(snapshot), path)
    reader = PdfReader(path)
    assert 10 <= count == len(reader.pages) <= 30
    assert all(len(" ".join(page.extract_text().split())) >= 300 for page in reader.pages)
