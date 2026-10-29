"""Bounded independent news search and optional broader web search.

Search results are leads, not verified facts. We never fetch arbitrary result
URLs, and they do not feed the headline factor or the archived scorecard.
"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from stock_crawler.models import NewsItem, WebResult
from stock_crawler.utils import text

USER_AGENT = "StockCrawler/1.1 (+https://github.com/Grobbit/Stock-Crawler; research)"
NEWS_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_RESPONSE = 2_000_000
_GDELT_LOCK = threading.Lock()
_GDELT_LAST_REQUEST = 0.0
_GDELT_INTERVAL = 5.1


def _company_name(info: dict) -> str:
    name = text(info.get("shortName") or info.get("longName"), 120)
    name = re.sub(r",?\s+\b(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|holdings)\.?$", "", name, flags=re.I).strip(" ,.")
    return name if 4 <= len(name) <= 100 and re.search(r"[A-Za-z]", name) else ""


def _matches_issuer(value: str, ticker: str, name: str) -> bool:
    if len(ticker) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", value):
        return True
    words = re.findall(r"[A-Za-z0-9]+", name)
    generic = {"the", "american", "international", "national", "united", "global", "first", "general", "new"}
    if not words:
        return False
    alias = " ".join(words[:2]) if words[0].lower() in generic and len(words) > 1 else words[0]
    return bool(len(alias) >= 4 and re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", value, re.I))


def _safe_result_url(value: str) -> str:
    try:
        parts = urlsplit(str(value))
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            return ""
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass  # A hostname, not a literal IP; result URLs are never fetched.
        return str(value)[:2000]
    except ValueError:
        return ""


def _bytes(response, limit: int = MAX_RESPONSE) -> bytes:
    try:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=32 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise ValueError("Search response too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def fetch_web_news(ticker: str, info: dict) -> tuple[list[NewsItem], list[str]]:
    """Search The GDELT Project's DOC API for recent issuer-matched leads.

    Respect the API's published limit of one request per five seconds across
    this single-process deployment. GDELT's seen date is not a publication date.
    """
    global _GDELT_LAST_REQUEST
    name = _company_name(info)
    query_name = re.sub(r"[^A-Za-z0-9 &.\-]", " ", name).strip()
    if len(query_name) < 4:
        return [], ["Independent news search was skipped because the issuer name was not established."]
    try:
        with _GDELT_LOCK:
            wait = _GDELT_INTERVAL - (time.monotonic() - _GDELT_LAST_REQUEST)
            if wait > 0:
                time.sleep(wait)
            _GDELT_LAST_REQUEST = time.monotonic()
        response = requests.get(
            NEWS_ENDPOINT,
            params={"query": f'"{query_name}" (stock OR earnings OR revenue OR customers OR company) sourcelang:english',
                    "mode": "artlist", "format": "json", "sort": "datedesc", "maxrecords": 60, "timespan": "3m"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=(5, 15), stream=True,
            allow_redirects=False,
        )
        payload = json.loads(_bytes(response))
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise ValueError("Unexpected news results")
        today = datetime.now(timezone.utc)
        results = []
        seen_titles, seen_urls = set(), set()
        for entry in articles[:60]:
            if not isinstance(entry, dict) or str(entry.get("language", "")).casefold() not in {"english", "en", "eng"}:
                continue
            title = text(entry.get("title"), 200)
            url = _safe_result_url(entry.get("url") or "")
            publisher = text((urlsplit(url).hostname or "").lower(), 70) if url else ""
            try:
                observed = datetime.strptime(str(entry.get("seendate", "")), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
            if not 0 <= (today - observed).total_seconds() <= 93 * 86400:
                continue
            if not title or not url or not _matches_issuer(title, ticker, name) or title.casefold() in seen_titles or url in seen_urls:
                continue
            seen_titles.add(title.casefold())
            seen_urls.add(url)
            results.append(NewsItem(title, publisher or "Publisher not supplied", observed.isoformat(), url, "en"))
            if len(results) == 18:
                break
        return results, [] if results else ["The GDELT Project news search returned no recent issuer-matched headlines."]
    except (requests.RequestException, ValueError, TypeError, AttributeError, OSError):
        return [], ["The GDELT Project news search was unavailable or rate-limited; current events should be checked separately."]


def _plain(value: object, limit: int) -> str:
    return text(html.unescape(re.sub(r"<[^>]*>", " ", str(value or ""))), limit)


def fetch_web_results(ticker: str, info: dict, api_key: str) -> tuple[list[WebResult], list[str]]:
    """Two topic-specific Brave Web searches when a server-side key is set."""
    if not api_key:
        return [], []
    name = _company_name(info)
    if not name:
        return [], ["Broader web search was skipped because the issuer name was not established."]
    queries = (
        ("Customers, products & growth", f'"{name}" {ticker} revenue customers products'),
        ("Strategy, risks & catalysts", f'"{name}" {ticker} competition risks strategy earnings'),
    )
    results: list[WebResult] = []
    seen: set[tuple[str, str]] = set()
    failures = 0
    for topic, query in queries:
        try:
            response = requests.get(BRAVE_ENDPOINT, params={"q": query, "count": 8, "search_lang": "en"},
                                    headers={"Accept": "application/json", "X-Subscription-Token": api_key,
                                             "User-Agent": USER_AGENT}, timeout=(5, 15), stream=True, allow_redirects=False)
            payload = json.loads(_bytes(response))
            items = payload.get("web", {}).get("results", [])
            if not isinstance(items, list):
                raise ValueError("Unexpected web results")
            for item in items:
                if not isinstance(item, dict):
                    continue
                title, snippet = _plain(item.get("title"), 160), _plain(item.get("description"), 260)
                url = _safe_result_url(item.get("url") or "")
                if not title or not url or not _matches_issuer(title + " " + snippet, ticker, name):
                    continue
                parts = urlsplit(url)
                key = ((parts.hostname or "").lower(), parts.path.rstrip("/"))
                if key in seen:
                    continue
                seen.add(key)
                published = _plain(item.get("page_age") or item.get("age"), 40) or "Date not supplied"
                results.append(WebResult(title, url, snippet, (parts.hostname or "").lower(), published, topic, "Brave Search"))
                if sum(result.topic == topic for result in results) >= 5:
                    break
        except (requests.RequestException, ValueError, TypeError, AttributeError, OSError):
            failures += 1
    warnings = []
    if failures:
        warnings.append("One or more broader web searches failed; check the search provider's key, quota and availability.")
    elif not results:
        warnings.append("The broader web search returned no issuer-matched results.")
    return results, warnings


def news_theme(title: str) -> str:
    """Simple topic buckets; a keyword match is not evidence that a claim is true."""
    patterns = (
        ("Results & guidance", r"earnings|revenue|profit|results|guidance|quarter|forecast"),
        ("Products & customers", r"product|customer|client|contract|launch|subscription|sales"),
        ("Competition & strategy", r"competit|rival|market share|acquisition|merger|partnership"),
        ("Legal, policy & risk", r"regulat|lawsuit|court|tariff|antitrust|cyber|investigation|risk"),
        ("Capital & leadership", r"ceo|executive|management|dividend|buyback|debt|capital|layoff"),
    )
    for label, pattern in patterns:
        if re.search(pattern, title, re.I):
            return label
    return "Other developments"
