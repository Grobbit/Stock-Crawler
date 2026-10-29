from datetime import date

from stock_crawler.models import AnnualFinancial, Filing
from stock_crawler.sources import sec


def test_sec_selects_latest_valid_filings_events_and_structured_facts(monkeypatch):
    recent = {
        # Deliberately out of order and includes invalid/future metadata.
        "form": ["10-K", "8-K", "10-Q", "8-K", "10-K"],
        "filingDate": ["2025-02-15", "2025-05-07", "2025-05-01", "2025-03-02", "2999-01-01"],
        "reportDate": ["2024-12-31", "2025-05-06", "2025-03-31", "2025-03-01", "2998-12-31"],
        "accessionNumber": ["0000000123-25-000001", "0000000123-25-000002", "0000000123-25-000003",
                            "0000000123-25-000004", "0000000123-99-000005"],
        "primaryDocument": ["annual.htm", "event.htm", "quarter.htm", "../bad.htm", "future.htm"],
        "items": ["", "2.02, 5.02", "", "2.01", ""],
    }
    calls = []
    def get_json(url, agent):
        assert agent == "Company researcher researcher@example.org"
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "TEST", "cik_str": 123}}
        if "/submissions/" in url:
            return {"filings": {"recent": recent}}
        assert "/companyfacts/" in url
        return {"cik": 123}
    def document(event, cik, agent):
        calls.append((event.form, event.url))
        return Filing(event.form, event.filing_date, event.report_date, event.url), []
    annual = AnnualFinancial(date(2024, 12, 31), 100, 20, 12, source="SEC XBRL", currency="USD")
    monkeypatch.setattr(sec, "_get_json", get_json)
    monkeypatch.setattr(sec, "_document", document)
    monkeypatch.setattr(sec, "parse_companyfacts", lambda facts, cik: ([annual], []))
    filing, warnings = sec.fetch_filing("TEST", "Company researcher researcher@example.org")
    assert not warnings and filing.form == "10-K" and filing.latest_quarter.form == "10-Q"
    assert [item.form for item in filing.recent_events] == ["8-K"]
    assert filing.recent_events[0].items == ("2.02", "5.02")
    assert filing.sec_annuals == (annual,) and filing.companyfacts_url.endswith("CIK0000000123.json")
    assert [form for form, _url in calls] == ["10-K", "10-Q"]


def test_filings_are_retained_when_facts_provider_fails(monkeypatch):
    recent = {"form": ["10-K"], "filingDate": ["2025-02-15"], "reportDate": ["2024-12-31"],
              "accessionNumber": ["0000000123-25-000001"], "primaryDocument": ["annual.htm"], "items": [""]}
    def get_json(url, agent):
        if "company_tickers.json" in url:
            return {"0": {"ticker": "TEST", "cik_str": 123}}
        if "/submissions/" in url:
            return {"filings": {"recent": recent}}
        raise ValueError("unavailable")
    monkeypatch.setattr(sec, "_get_json", get_json)
    monkeypatch.setattr(sec, "_document", lambda event, *_: (Filing(event.form, event.filing_date, event.report_date, event.url), []))
    filing, warnings = sec.fetch_filing("TEST", "Real Name real@example.org")
    assert filing.form == "10-K" and not filing.sec_annuals
    assert "structured company facts" in warnings[0]


def test_sec_excerpt_preserves_sentence_context_and_ignores_hidden_text():
    data = b'''<html><ix:header><span>Revenue increased due primarily to hidden XBRL values of 9999 percent.</span></ix:header>
      <p>For example, tensions between governments, including the U.S. and China, have in the past led to tariffs and other restrictions affecting the Company's business.</p>
      <p>Widget Widget net sales increased during 2024 compared to 2023 due primarily to higher net sales of subscriptions.</p>
      <p>The company depends on cybersecurity and security incidents could adversely affect business operations.</p></html>'''
    _customers, risks, policies, operations = sec._extract_disclosures(data)
    assert policies[0].startswith("For example, tensions between governments, including the U.S.")
    assert operations[0].startswith("Widget net sales increased")
    assert all("9999" not in excerpt for excerpt in risks + policies + operations)


def test_bounded_sec_read_closes_response_even_when_truncated():
    class Response:
        closed = False
        def raise_for_status(self): pass
        def iter_content(self, chunk_size):
            yield b"abcdefgh"
            yield b"ijklmnop"
        def close(self): self.closed = True
    response = Response()
    content, truncated = sec._read_bounded(response, 10)
    assert content == b"abcdefghij" and truncated and response.closed
