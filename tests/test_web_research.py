import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from stock_crawler.sources import web_research, wikidata


class Response:
    def __init__(self, value, status=200):
        self.value = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.status = status
        self.closed = False
    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError("upstream failure")
    def iter_content(self, chunk_size):
        yield self.value
    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def no_news_delay(monkeypatch):
    monkeypatch.setattr(web_research, "_GDELT_INTERVAL", 0)


def test_gdelt_search_is_dated_issuer_matched_deduplicated_and_safe(monkeypatch):
    now = datetime.now(timezone.utc)
    def entry(title, date, url, language="English"):
        return {"title": title, "seendate": date.strftime("%Y%m%dT%H%M%SZ"), "url": url, "language": language}
    body = {"articles": [
        entry("Apple announces a new product", now - timedelta(days=2), "https://example.com/apple"),
        entry("Apple announces a new product", now - timedelta(days=2), "https://example.com/duplicate"),
        entry("Apple old results", now - timedelta(days=100), "https://example.com/old"),
        entry("Apple future results", now + timedelta(days=1), "https://example.com/future"),
        entry("Unrelated company reports results", now - timedelta(days=2), "https://example.com/wrong"),
        entry("Apple unsafe link", now - timedelta(days=2), "http://127.0.0.1/internal"),
        entry("Apple a new product", now - timedelta(days=2), "https://example.com/french", "French"),
    ]}
    captured = []
    def get(url, **kwargs):
        captured.append((url, kwargs))
        return Response(body)
    monkeypatch.setattr(web_research.requests, "get", get)
    results, warnings = web_research.fetch_web_news("AAPL", {"longName": "Apple Inc."})
    assert not warnings and len(results) == 1
    assert results[0].title == "Apple announces a new product"
    assert results[0].publisher == "example.com" and results[0].language == "en"
    assert results[0].url == "https://example.com/apple"
    assert '"Apple"' in captured[0][1]["params"]["query"]
    assert captured[0][1]["allow_redirects"] is False
    assert web_research.news_theme(results[0].title) == "Products & customers"


def test_gdelt_rate_limit_or_bad_response_fails_gracefully(monkeypatch):
    monkeypatch.setattr(web_research.requests, "get", lambda *_a, **_kw: Response(b"Please limit requests to one every 5 seconds"))
    results, warnings = web_research.fetch_web_news("AAPL", {"longName": "Apple Inc."})
    assert results == [] and "unavailable or rate-limited" in warnings[0]
    assert web_research.fetch_web_news("AAPL", {})[0] == []


def test_gdelt_requests_are_spaced_across_reports(monkeypatch):
    monkeypatch.setattr(web_research, "_GDELT_INTERVAL", 5.1)
    monkeypatch.setattr(web_research, "_GDELT_LAST_REQUEST", 100.0)
    monkeypatch.setattr(web_research.time, "monotonic", lambda: 102.0)
    waits = []
    monkeypatch.setattr(web_research.time, "sleep", waits.append)
    monkeypatch.setattr(web_research.requests, "get", lambda *_a, **_kw: Response({"articles": []}))
    web_research.fetch_web_news("AAPL", {"longName": "Apple Inc."})
    assert waits == pytest.approx([3.1])


def test_brave_key_stays_in_header_and_results_are_unverified_leads(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"web": {"results": [
            {"title": "Apple business expansion", "url": "https://example.com/apple", "description": "<strong>Apple</strong> added new products", "age": "2 days ago"},
            {"title": "Unrelated headline", "url": "https://example.com/other", "description": "A different company"},
            {"title": "Apple unsafe", "url": "http://127.0.0.1/internal", "description": "Apple"},
            {"title": "Apple script URL", "url": "javascript:alert(1)", "description": "Apple"},
        ]}})
    monkeypatch.setattr(web_research.requests, "get", get)
    results, warnings = web_research.fetch_web_results("AAPL", {"longName": "Apple Inc."}, "super-secret")
    assert not warnings and len(results) == 1  # duplicate URL across searches removed
    assert results[0].snippet == "Apple added new products"
    assert results[0].source == "Brave Search" and results[0].published_at == "2 days ago"
    assert len(calls) == 2
    for url, kwargs in calls:
        assert url == web_research.BRAVE_ENDPOINT
        assert kwargs["headers"]["X-Subscription-Token"] == "super-secret"
        assert kwargs["allow_redirects"] is False
        assert "super-secret" not in str(kwargs["params"])
    assert web_research.fetch_web_results("AAPL", {}, "")[0] == []


def test_brave_failure_does_not_expose_key_or_crash(monkeypatch):
    monkeypatch.setattr(web_research.requests, "get", lambda *_a, **_kw: Response({}, status=401))
    results, warnings = web_research.fetch_web_results("AAPL", {"longName": "Apple Inc."}, "secret-value")
    assert not results and "failed" in warnings[0]
    assert "secret-value" not in str(warnings)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://localhost/", "http://192.168.1.1/", "http://[::1]/", "https://user:pass@example.com/"])
def test_bad_result_links_are_not_shown(url):
    assert not web_research._safe_result_url(url)


def _claim(value, *, qualifiers=None, rank="normal"):
    item = {"mainsnak": {"datavalue": {"value": value}}, "rank": rank}
    if qualifiers:
        item["qualifiers"] = qualifiers
    return item


def _entity(ticker="AAPL"):
    return {"labels": {"en": {"value": "Apple Inc."}}, "claims": {
        "P249": [_claim(ticker)],
        "P1056": [_claim({"id": "Q1"}), _claim({"id": "Q2"}, qualifiers={"P582": [{"datavalue": {"value": {"time": "+2000-01-01T00:00:00Z"}}}]})],
        "P355": [_claim({"id": "Q3"})],
        "P112": [_claim({"id": "Q4"})],
        "P571": [_claim({"time": "+1976-04-01T00:00:00Z"})],
    }}


def test_wikidata_requires_ticker_and_name_before_extracting_context(monkeypatch):
    calls = []
    def api(params):
        calls.append(params)
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": "Q100"}]}
        if params["props"] == "labels|claims":
            return {"entities": {"Q100": _entity()}}
        return {"entities": {"Q1": {"labels": {"en": {"value": "iPhone"}}},
                             "Q3": {"labels": {"en": {"value": "Example subsidiary"}}},
                             "Q4": {"labels": {"en": {"value": "Example founder"}}}}}
    monkeypatch.setattr(wikidata, "_api", api)
    profile, warnings = wikidata.fetch_company_profile("AAPL", {"longName": "Apple Inc."})
    assert not warnings and profile.entity_id == "Q100"
    assert profile.products == ("iPhone",)  # Ended product was excluded.
    assert profile.subsidiaries == ("Example subsidiary",)
    assert profile.founders == ("Example founder",) and profile.inception == "1976"
    assert len(calls) == 3


def test_wikidata_withholds_wrong_or_ambiguous_identity(monkeypatch):
    def api(params):
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": "Q100"}, {"id": "Q101"}]}
        return {"entities": {"Q100": _entity("WRONG"), "Q101": _entity("OTHER")}}
    monkeypatch.setattr(wikidata, "_api", api)
    profile, warnings = wikidata.fetch_company_profile("AAPL", {"longName": "Apple Inc."})
    assert profile is None and "withheld" in warnings[0]
    monkeypatch.setattr(wikidata, "_api", lambda params: {"search": [{"id": "Q100"}, {"id": "Q101"}]}
                        if params["action"] == "wbsearchentities" else {"entities": {"Q100": _entity(), "Q101": _entity()}})
    assert wikidata.fetch_company_profile("AAPL", {"longName": "Apple Inc."})[0] is None


def test_wikidata_accepts_ticker_qualifier_on_exchange_claim():
    entity = {"claims": {"P414": [_claim({"id": "Qexchange"}, qualifiers={"P249": [{"datavalue": {"value": "AAPL"}}]})]}}
    assert wikidata._tickers(entity) == {"AAPL"}
