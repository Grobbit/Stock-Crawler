"""Optional keyless, identity-checked company context from Wikidata.

Wikidata is community-maintained and may be stale. We require both a provider
name match and an exact ticker claim; unverified entities are withheld.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

import requests

from stock_crawler.models import CompanyProfile
from stock_crawler.sources.web_research import USER_AGENT, _bytes, _company_name
from stock_crawler.utils import text

API = "https://www.wikidata.org/w/api.php"


def _api(params):
    response = requests.get(API, params={"format": "json", "maxlag": 5, **params},
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                            timeout=(5, 12), stream=True)
    payload = json.loads(_bytes(response, 5_000_000))
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("Wikidata query failed")
    return payload


def _name_matches(left: str, right: str) -> bool:
    def normalized(value):
        value = re.sub(r"\b(?:incorporated|inc|corporation|corp|company|co|ltd|limited|plc)\b", " ", value, flags=re.I)
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    a, b = normalized(left), normalized(right)
    if not a or not b or min(len(a), len(b)) < 4:
        return False
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.75


def _active(claim: dict, current_year: int) -> bool:
    if claim.get("rank") == "deprecated":
        return False
    for end in claim.get("qualifiers", {}).get("P582", []):
        value = end.get("datavalue", {}).get("value", {})
        raw = value.get("time", "") if isinstance(value, dict) else ""
        match = re.match(r"\+(\d{4})-", raw)
        if not match or int(match.group(1)) <= current_year:
            return False
    return True


def _value(snak: dict):
    return snak.get("datavalue", {}).get("value") if isinstance(snak, dict) else None


def _tickers(entity: dict) -> set[str]:
    current_year = datetime.now(timezone.utc).year
    result = set()
    claims = entity.get("claims", {})
    for claim in claims.get("P249", []):
        value = _value(claim.get("mainsnak", {}))
        if _active(claim, current_year) and isinstance(value, str):
            result.add(value.upper().replace(".", "-"))
    for claim in claims.get("P414", []):
        if not _active(claim, current_year):
            continue
        for qualifier in claim.get("qualifiers", {}).get("P249", []):
            value = _value(qualifier)
            if isinstance(value, str):
                result.add(value.upper().replace(".", "-"))
    return result


def fetch_company_profile(ticker: str, info: dict) -> tuple[CompanyProfile | None, list[str]]:
    name = _company_name(info)
    if not name:
        return None, ["Wikidata company context was skipped because the issuer name was not established."]
    try:
        search = _api({"action": "wbsearchentities", "search": name, "language": "en", "type": "item", "limit": 5})
        ids = [item.get("id", "") for item in search.get("search", []) if isinstance(item, dict)]
        ids = [item for item in ids if re.fullmatch(r"Q[1-9]\d*", item)][:5]
        if not ids:
            return None, ["Wikidata did not provide an identity-matched company profile."]
        response = _api({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|claims", "languages": "en"})
        entities = response.get("entities", {})
        matches = []
        for entity_id in ids:
            entity = entities.get(entity_id, {})
            label = entity.get("labels", {}).get("en", {}).get("value", "")
            if _name_matches(name, label) and ticker.upper().replace(".", "-") in _tickers(entity):
                matches.append((entity_id, label, entity))
        if len(matches) != 1:
            return None, ["Wikidata company context was withheld because the ticker and company identity could not be uniquely verified."]
        entity_id, label, entity = matches[0]
        claims = entity.get("claims", {})
        current_year = datetime.now(timezone.utc).year
        groups = {}
        for prop, limit in (("P1056", 5), ("P355", 4), ("P112", 4)):
            values = []
            for claim in claims.get(prop, []):
                if prop != "P112" and not _active(claim, current_year):
                    continue
                if claim.get("rank") == "deprecated":
                    continue
                value = _value(claim.get("mainsnak", {}))
                target = value.get("id", "") if isinstance(value, dict) else ""
                if re.fullmatch(r"Q[1-9]\d*", target) and target not in values:
                    values.append(target)
                if len(values) == limit:
                    break
            groups[prop] = values
        targets = list(dict.fromkeys(item for values in groups.values() for item in values))
        labels = {}
        if targets:
            data = _api({"action": "wbgetentities", "ids": "|".join(targets), "props": "labels", "languages": "en"})
            labels = {key: text(value.get("labels", {}).get("en", {}).get("value"), 80)
                      for key, value in data.get("entities", {}).items() if isinstance(value, dict)}
        def names(prop):
            return tuple(labels[identifier] for identifier in groups[prop] if labels.get(identifier))
        inception = ""
        for claim in claims.get("P571", []):
            value = _value(claim.get("mainsnak", {}))
            raw = value.get("time", "") if isinstance(value, dict) else ""
            match = re.match(r"\+(\d{4})-", raw)
            if claim.get("rank") != "deprecated" and match:
                inception = match.group(1)
                break
        profile = CompanyProfile(entity_id, text(label, 100), names("P1056"), names("P355"), names("P112"),
                                 inception, datetime.now(timezone.utc))
        return profile, []
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError, OSError):
        return None, ["Wikidata company context was unavailable or could not be verified."]
