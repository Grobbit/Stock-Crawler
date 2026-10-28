"""Current elected officials and historical presidential terms, not policy guesses.

The public, CC0 unitedstates/congress-legislators data are retrieved by GitHub
API, with a short in-process cache. Dates in this source describe recorded
terms; readers should check official sources for vacancies or later changes.
"""
from __future__ import annotations

import base64
import threading
import time
from datetime import date, datetime, timezone

import requests
import yaml

from stock_crawler.models import Official, PoliticalContext
from stock_crawler.utils import text

API = "https://api.github.com/repos/unitedstates/congress-legislators"
SOURCE = "https://github.com/unitedstates/congress-legislators"
CACHE_SECONDS = 6 * 60 * 60
# Each entry keeps both the monotonic expiry and actual UTC fetch time, so a
# report using cached records does not label old data as freshly retrieved.
_cache: dict[str, tuple[float, datetime, list]] = {}
_lock = threading.Lock()
STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}
LEADERS = ("Speaker of the House", "House Majority Leader", "House Minority Leader",
           "Senate Majority Leader", "Senate Minority Leader")


def _get_json(url: str) -> dict:
    response = requests.get(url, headers={"User-Agent": "StockCrawler/1.1 (public research)",
                                          "Accept": "application/vnd.github+json"}, timeout=(5, 15))
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected GitHub data")
    return data


def _get_dataset(filename: str) -> list:
    if filename not in {"executive.yaml", "legislators-current.yaml"}:
        raise ValueError("Unknown political dataset")
    with _lock:
        cached = _cache.get(filename)
        if cached and time.monotonic() < cached[0]:
            return cached[2]
        metadata = _get_json(f"{API}/contents/{filename}")
        # GitHub's contents endpoint omits base64 for files >1 MB; its blob API
        # supplies the same repository object, without relying on a raw host.
        if metadata.get("encoding") != "base64" or not metadata.get("content"):
            sha = metadata.get("sha")
            if not isinstance(sha, str) or not sha.isalnum():
                raise ValueError("Missing blob identifier")
            metadata = _get_json(f"{API}/git/blobs/{sha}")
        encoded = metadata.get("content")
        if not isinstance(encoded, str) or len(encoded) > 3_000_000:
            raise ValueError("Political data missing or too large")
        parsed = yaml.safe_load(base64.b64decode(encoded))
        if not isinstance(parsed, list):
            raise ValueError("Unexpected political data")
        _cache[filename] = (time.monotonic() + CACHE_SECONDS, datetime.now(timezone.utc), parsed)
        return parsed


def _date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _active(term: dict, day: date) -> bool:
    start, end = _date(term.get("start")), _date(term.get("end"))
    return start is not None and start <= day and (end is None or day < end)


def _name(person: dict) -> str:
    name = person.get("name") or {}
    if not isinstance(name, dict):
        return "Unknown"
    return text(name.get("official_full") or " ".join(filter(None, [name.get("nickname") or name.get("first"), name.get("last")])), 100) or "Unknown"


def parse_political_context(executive: list, legislators: list, info: dict, as_of: date,
                            retrieved_at: datetime | None = None) -> PoliticalContext:
    context = PoliticalContext(retrieved_at=retrieved_at or datetime.now(timezone.utc))
    for person in executive:
        if not isinstance(person, dict):
            continue
        name = _name(person)
        for term in person.get("terms", []):
            if not isinstance(term, dict) or term.get("type") not in {"prez", "viceprez"}:
                continue
            start = _date(term.get("start"))
            if not start:
                continue
            party = text(term.get("party"), 45) or "Not specified"
            if _active(term, as_of):
                role = "President" if term["type"] == "prez" else "Vice president"
                context.executives.append(Official(name, role, party, start, _date(term.get("end"))))
            if term["type"] == "prez" and term.get("how") == "election" and start.month == 1:
                # A January presidential term follows the preceding November's
                # election; do not infer a future result before its election.
                election_year = start.year - 1
                if start <= as_of and election_year % 4 == 0:
                    context.presidential_winners[election_year] = (name, party)
    context.executives.sort(key=lambda official: 0 if official.role == "President" else 1)

    country = text(info.get("country"), 80).upper()
    state = text(info.get("state"), 50).upper()
    if country in {"UNITED STATES", "UNITED STATES OF AMERICA", "USA", "US"}:
        context.headquarters_state = STATES.get(state, state if state in STATES.values() else "")
    for person in legislators:
        if not isinstance(person, dict):
            continue
        terms = [term for term in person.get("terms", []) if isinstance(term, dict) and _active(term, as_of)]
        if not terms:
            continue
        term = terms[-1]
        name = _name(person)
        party = text(term.get("party"), 45) or "Not specified"
        state = text(term.get("state"), 3)
        start = _date(term.get("start"))
        if not start:
            continue
        if term.get("type") == "sen" and state == context.headquarters_state and state:
            context.headquarters_senators.append(Official(name, "US senator", party, start, _date(term.get("end")), state))
        for role in person.get("leadership_roles", []):
            if isinstance(role, dict) and role.get("title") in LEADERS and _active(role, as_of):
                role_start = _date(role.get("start")) or start
                context.leaders.append(Official(name, role["title"], party, role_start, _date(role.get("end")), state))
    context.leaders.sort(key=lambda official: LEADERS.index(official.role))
    context.headquarters_senators.sort(key=lambda official: official.name)
    return context


def fetch_political_context(info: dict) -> tuple[PoliticalContext | None, list[str]]:
    warnings: list[str] = []
    try:
        executive = _get_dataset("executive.yaml")
    except (requests.RequestException, ValueError, TypeError, yaml.YAMLError, OSError):
        executive = []
        warnings.append("US executive-branch data were unavailable; current officeholders and election winners may be missing.")
    try:
        legislators = _get_dataset("legislators-current.yaml")
    except (requests.RequestException, ValueError, TypeError, yaml.YAMLError, OSError):
        legislators = []
        warnings.append("US congressional data were unavailable; leadership and headquarters-state senators may be missing.")
    if not executive and not legislators:
        return None, warnings
    now = datetime.now(timezone.utc)
    with _lock:
        fetched = [entry[1] for name, data in (("executive.yaml", executive), ("legislators-current.yaml", legislators))
                   if data and (entry := _cache.get(name))]
    # Conservative source date when the two datasets were fetched at
    # different times; tests or custom loaders may not populate the cache.
    context = parse_political_context(executive, legislators, info, now.date(), min(fetched) if fetched else now)
    return context, warnings
