"""
Module 5 data layer — RSS feeds + Nitter + periodic scrape sources.
Returns ContentItem list consumed by scorer.py.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import random
import time
import feedparser
import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Items older than this are excluded before scoring
MAX_AGE_HOURS = 48


@dataclass
class ContentItem:
    title: str
    url: str
    source_name: str
    source_tier: str
    published: datetime
    summary: str
    word_count: int
    position_tags: list = field(default_factory=list)
    # filled by scorer
    score: float = 0.0


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.5",
    }


def _parse_date(entry) -> Optional[datetime]:
    """Best-effort parse of feedparser's published_parsed or updated_parsed."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            import calendar
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def _entry_to_item(entry, source_name: str, source_tier: str, position_tags: list) -> Optional[ContentItem]:
    title = getattr(entry, "title", "").strip()
    url = getattr(entry, "link", "").strip()
    if not title or not url:
        return None

    published = _parse_date(entry)
    if published is None:
        published = datetime.now(timezone.utc)

    # Check age
    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    if age_hours > MAX_AGE_HOURS:
        return None

    # Summary: prefer summary over content, truncate to first 400 words
    raw_summary = getattr(entry, "summary", "") or ""
    if not raw_summary:
        content = getattr(entry, "content", [])
        if content:
            raw_summary = content[0].get("value", "")
    # Strip HTML tags
    if raw_summary:
        soup = BeautifulSoup(raw_summary, "lxml")
        raw_summary = soup.get_text(separator=" ", strip=True)
    words = raw_summary.split()
    summary = " ".join(words[:400])
    word_count = len(words)

    return ContentItem(
        title=title,
        url=url,
        source_name=source_name,
        source_tier=source_tier,
        published=published,
        summary=summary,
        word_count=word_count,
        position_tags=position_tags,
    )


def _fetch_rss(url: str, source_name: str, source_tier: str, position_tags: list) -> list[ContentItem]:
    try:
        time.sleep(random.uniform(0.3, 0.8))
        feed = feedparser.parse(url, request_headers=_random_headers())
        items = []
        for entry in feed.entries:
            item = _entry_to_item(entry, source_name, source_tier, position_tags)
            if item:
                items.append(item)
        return items
    except Exception:
        return []


def _fetch_nitter(nitter_url: str, handle: str, position_tags: list) -> list[ContentItem]:
    """Fetch Twitter account via Nitter RSS. Treats each tweet as a content item."""
    items = _fetch_rss(
        url=nitter_url,
        source_name=f"@{handle}",
        source_tier="tier_3",
        position_tags=position_tags,
    )
    # Tweets are short — word_count will naturally be low, scored accordingly
    return items


def fetch_content(sources: dict) -> list[ContentItem]:
    """Fetch all sources from sources.yml and return flat ContentItem list."""
    all_items: list[ContentItem] = []

    # Central banks (tier_1)
    for src in sources.get("central_banks", []):
        rss = src.get("rss") or src.get("url")
        if not rss:
            continue
        items = _fetch_rss(rss, src["name"], "tier_1", [])
        all_items.extend(items)

    # Buy-side (tier_2) — skip quarterly/monthly unless recently updated
    for src in sources.get("buyside", []):
        freq = src.get("scrape_frequency", "daily")
        rss = src.get("rss")
        url = src.get("url")
        tags = src.get("position_tags", [])
        if rss:
            all_items.extend(_fetch_rss(rss, src["name"], "tier_2", tags))
        elif url and freq == "daily":
            # Scrape HTML for link list — best effort
            all_items.extend(_scrape_html_links(url, src["name"], "tier_2", tags))

    # Independent macro (tier_2)
    for src in sources.get("independent", []):
        rss = src.get("rss")
        tags = src.get("position_tags", [])
        if rss:
            all_items.extend(_fetch_rss(rss, src["name"], "tier_2", tags))

    # Twitter via Nitter (tier_3)
    for src in sources.get("twitter", []):
        nitter_url = src.get("nitter_url")
        tags = src.get("position_tags", [])
        if nitter_url:
            all_items.extend(_fetch_nitter(nitter_url, src.get("handle", ""), tags))

    return all_items


def _scrape_html_links(url: str, source_name: str, source_tier: str, position_tags: list) -> list[ContentItem]:
    """Scrape a research library page for recent article links. Best-effort."""
    try:
        time.sleep(random.uniform(1.0, 2.0))
        resp = requests.get(url, headers=_random_headers(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        items = []
        for a in soup.find_all("a", href=True)[:20]:
            title = a.get_text(strip=True)
            href = a["href"]
            if not title or len(title) < 10:
                continue
            if not href.startswith("http"):
                from urllib.parse import urljoin
                href = urljoin(url, href)
            items.append(ContentItem(
                title=title,
                url=href,
                source_name=source_name,
                source_tier=source_tier,
                published=datetime.now(timezone.utc),
                summary="",
                word_count=0,
                position_tags=position_tags,
            ))
        return items[:5]
    except Exception:
        return []
