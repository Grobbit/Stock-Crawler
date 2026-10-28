import base64
from datetime import datetime, timezone

from stock_crawler.sources import politics


def person(name, terms, roles=None):
    return {"name": {"official_full": name}, "terms": terms, "leadership_roles": roles or []}


def test_political_parser_dated_roles_winners_and_headquarters_state():
    executive = [
        person("Past President", [{"type": "prez", "start": "2021-01-20", "end": "2025-01-20", "party": "A", "how": "election"}]),
        person("Current President", [{"type": "prez", "start": "2025-01-20", "end": "2029-01-20", "party": "B", "how": "election"}]),
        person("Current Vice President", [{"type": "viceprez", "start": "2025-01-20", "end": "2029-01-20", "party": "B"}]),
        person("Future President", [{"type": "prez", "start": "2029-01-20", "end": "2033-01-20", "party": "C", "how": "election"}]),
        person("Succession President", [{"type": "prez", "start": "2023-01-01", "end": "2023-02-01", "party": "X", "how": "succession"}]),
    ]
    legislators = [
        person("CA Senator", [{"type": "sen", "state": "CA", "start": "2023-01-03", "end": "2029-01-03", "party": "A"}],
               [{"title": "Senate Minority Leader", "start": "2025-01-03"}]),
        person("Speaker", [{"type": "rep", "state": "OR", "start": "2025-01-03", "end": "2027-01-03", "party": "B"}],
               [{"title": "Speaker of the House", "start": "2025-01-03"}]),
        person("Expired CA Senator", [{"type": "sen", "state": "CA", "start": "2019-01-03", "end": "2025-01-03", "party": "A"}]),
        person("Other Senator", [{"type": "sen", "state": "OR", "start": "2023-01-03", "end": "2029-01-03", "party": "B"}]),
    ]
    retrieved = datetime(2025, 2, 1, tzinfo=timezone.utc)
    context = politics.parse_political_context(executive, legislators, {"country": "United States", "state": "California"}, retrieved.date(), retrieved)
    assert [item.name for item in context.executives] == ["Current President", "Current Vice President"]
    assert context.presidential_winners == {2020: ("Past President", "A"), 2024: ("Current President", "B")}
    assert [item.role for item in context.leaders] == ["Speaker of the House", "Senate Minority Leader"]
    assert context.headquarters_state == "CA"
    assert [item.name for item in context.headquarters_senators] == ["CA Senator"]
    assert context.retrieved_at == retrieved

    foreign = politics.parse_political_context(executive, legislators, {"country": "Canada", "state": "CA"}, retrieved.date())
    assert not foreign.headquarters_state and not foreign.headquarters_senators


def test_github_blob_fallback_and_cache(monkeypatch):
    calls = []
    content = base64.b64encode(b"- name:\n    official_full: Example\n  terms: []\n").decode()
    def fake_get(url):
        calls.append(url)
        if "/contents/" in url:
            return {"sha": "abc123", "encoding": "none"}
        return {"content": content, "encoding": "base64"}
    monkeypatch.setattr(politics, "_cache", {})
    monkeypatch.setattr(politics, "_get_json", fake_get)
    first = politics._get_dataset("legislators-current.yaml")
    assert first[0]["name"]["official_full"] == "Example"
    fetched_at = politics._cache["legislators-current.yaml"][1]
    assert politics._get_dataset("legislators-current.yaml") == first
    assert politics._cache["legislators-current.yaml"][1] == fetched_at
    assert len(calls) == 2 and calls[1].endswith("/git/blobs/abc123")


def test_political_source_partial_failure_is_not_fabricated(monkeypatch):
    executive = [person("President", [{"type": "prez", "start": "2025-01-20", "end": "2030-01-20", "party": "A", "how": "election"}])]
    def fake_data(filename):
        if filename == "executive.yaml":
            return executive
        raise ValueError("failed")
    monkeypatch.setattr(politics, "_get_dataset", fake_data)
    context, warnings = politics.fetch_political_context({"country": "United States", "state": "CA"})
    assert context is not None and len(warnings) == 1
    assert not context.leaders and not context.headquarters_senators
    assert "congressional data" in warnings[0]


def test_political_context_displays_oldest_actual_dataset_fetch_time(monkeypatch):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=5)
    newer = now - timedelta(hours=2)
    executive = [person("President", [{"type": "prez", "start": "2025-01-20", "end": "2030-01-20", "party": "A"}])]
    legislators = [person("Senator", [{"type": "sen", "state": "MI", "start": "2025-01-03", "end": "2031-01-03", "party": "B"}])]
    monkeypatch.setattr(politics, "_cache", {
        "executive.yaml": (float("inf"), older, executive),
        "legislators-current.yaml": (float("inf"), newer, legislators),
    })
    context, warnings = politics.fetch_political_context({"country": "United States", "state": "MI"})
    assert not warnings and context.retrieved_at == older
    assert [official.name for official in context.headquarters_senators] == ["Senator"]
