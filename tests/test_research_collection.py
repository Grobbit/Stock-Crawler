from dataclasses import replace

from stock_crawler import collector
from stock_crawler.analysis import analyze
from stock_crawler.demo import demo_snapshot


def _mock_collection(monkeypatch, snapshot):
    monkeypatch.setattr(collector, "fetch_market", lambda _ticker: (snapshot.info, snapshot.prices, [], [], snapshot.price_source))
    monkeypatch.setattr(collector, "fetch_macro", lambda: (snapshot.macro, snapshot.macro_history, []))
    monkeypatch.setattr(collector, "fetch_filing", lambda *_: (snapshot.filing, ["filing note"]))
    monkeypatch.setattr(collector, "fetch_annual_financials", lambda *_: (snapshot.annuals, []))
    monkeypatch.setattr(collector, "fetch_quarterly_financials", lambda *_: (snapshot.quarters, ["quarter note"]))
    monkeypatch.setattr(collector, "fetch_news", lambda *_: (snapshot.news, []))
    monkeypatch.setattr(collector, "fetch_web_news", lambda *_: (snapshot.web_news, ["independent note"]))
    monkeypatch.setattr(collector, "fetch_company_profile", lambda *_: (snapshot.company_profile, ["profile note"]))
    monkeypatch.setattr(collector, "fetch_political_context", lambda *_: (snapshot.politics, []))
    monkeypatch.setattr(collector, "fetch_benchmark", lambda: (snapshot.benchmark_prices, []))
    monkeypatch.setattr(collector, "fetch_options", lambda *_: (snapshot.options, []))
    monkeypatch.setattr(collector, "fetch_analyst_trend", lambda *_: (snapshot.analyst_trend, []))
    monkeypatch.setattr(collector, "fetch_peers", lambda *_: (snapshot.peers, []))
    monkeypatch.setattr(collector, "load_signals", lambda *_: ([], []))


def test_collector_stores_new_evidence_and_warnings(monkeypatch):
    demo = demo_snapshot()
    _mock_collection(monkeypatch, demo)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "private-test-key")
    calls = []
    def web(ticker, info, key):
        calls.append((ticker, info, key))
        return demo.web_results, ["search note"]
    monkeypatch.setattr(collector, "fetch_web_results", web)
    result = collector.collect("DEMO")
    assert result.quarters == demo.quarters and result.filing == demo.filing
    assert result.web_news == demo.web_news and result.web_results == demo.web_results
    assert result.company_profile == demo.company_profile and result.web_search_enabled
    assert {"filing note", "quarter note", "independent note", "search note", "profile note"}.issubset(result.warnings)
    assert calls == [("DEMO", demo.info, "private-test-key")]
    assert "private-test-key" not in str(result.warnings)


def test_optional_brave_provider_is_not_called_without_key(monkeypatch):
    demo = demo_snapshot()
    _mock_collection(monkeypatch, demo)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    def fail_if_called(*_args):
        raise AssertionError("Brave should not be contacted")
    monkeypatch.setattr(collector, "fetch_web_results", fail_if_called)
    result = collector.collect("DEMO")
    assert result.web_results == [] and not result.web_search_enabled


def test_richer_unscored_research_does_not_revise_scorecard():
    base = demo_snapshot()
    enriched = demo_snapshot()
    enriched.web_news = []
    enriched.web_results = []
    enriched.company_profile = None
    enriched.quarters = []
    enriched.filing = replace(enriched.filing, revenue_breakdowns=(), operating_excerpts=(), sec_annuals=(), sec_quarters=())
    before, after = analyze(base), analyze(enriched)
    assert before.score == after.score and before.verdict == after.verdict
    assert before.factors == after.factors and before.ranges == after.ranges
    assert before.research_insights != after.research_insights
