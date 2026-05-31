"""
Module 5 data layer — RSS feeds + NewsAPI + GDELT.
Returns ContentItem list consumed by scorer.py.

Source tiers:
  tier_1 — Central banks / supranational (always scraped)
  tier_2 — Buy-side / independent macro (RSS)
  tier_3 — Dynamic (NewsAPI keyword search, GDELT broad sweep)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
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

MAX_AGE_HOURS = 48

# Domains the PM already reads — excluded from NewsAPI results
MAINSTREAM_EXCLUDE = [
    "bloomberg.com", "reuters.com", "ft.com", "wsj.com",
    "cnbc.com", "businessinsider.com", "marketwatch.com",
    "economist.com", "nytimes.com", "theguardian.com",
]

# Maps position.yml tags → human-readable search terms for NewsAPI / GDELT
TAG_TERMS = {
    "JPY":        "yen",
    "BOJ":        "Bank of Japan",
    "UST":        "treasury bonds",
    "fiscal":     "fiscal deficit",
    "EM":         "emerging markets",
    "gold":       "gold",
    "real_rates": "real rates",
    "dollar":     "US dollar",
    "rates":      "interest rates",
    "duration":   "bond duration",
    "eurodollar": "eurodollar",
    "BRL":        "Brazil",
    "INR":        "India",
    "IDR":        "Indonesia",
    "geopolitics":"geopolitics",
    "energy":     "energy",
    "inflation":  "inflation",
    "liquidity":  "liquidity",
    "carry":      "carry trade",
    "macro":      "macro economy",
}


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
    score: float = 0.0


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.5",
    }


def _parse_date(entry) -> Optional[datetime]:
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

    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    if age_hours > MAX_AGE_HOURS:
        return None

    raw_summary = getattr(entry, "summary", "") or ""
    if not raw_summary:
        content = getattr(entry, "content", [])
        if content:
            raw_summary = content[0].get("value", "")
    if raw_summary:
        soup = BeautifulSoup(raw_summary, "lxml")
        raw_summary = soup.get_text(separator=" ", strip=True)
    words = raw_summary.split()

    return ContentItem(
        title=title,
        url=url,
        source_name=source_name,
        source_tier=source_tier,
        published=published,
        summary=" ".join(words[:400]),
        word_count=len(words),
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


def _build_tag_query(positions: list[dict], max_terms: int = 6) -> tuple[str, list[str]]:
    """
    Convert positions list to a search query string and flat tag list.
    Returns (query_string, all_tags).
    """
    all_tags: list[str] = []
    for p in positions:
        all_tags.extend(p.get("tags", []))
    all_tags = list(dict.fromkeys(all_tags))  # dedupe preserving order

    terms = []
    seen = set()
    for tag in all_tags:
        term = TAG_TERMS.get(tag, tag)
        if term not in seen:
            seen.add(term)
            terms.append(f'"{term}"' if " " in term else term)
        if len(terms) >= max_terms:
            break

    return " OR ".join(terms), all_tags


def _fetch_newsapi(positions: list[dict], api_key: str) -> list[ContentItem]:
    """
    Search NewsAPI for articles matching position tags from the last 24h.
    Excludes mainstream outlets the PM already reads.
    """
    if not api_key or not positions:
        return []

    query, all_tags = _build_tag_query(positions, max_terms=6)
    if not query:
        return []

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    try:
        time.sleep(random.uniform(0.5, 1.0))
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": yesterday,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 25,
                "excludeDomains": ",".join(MAINSTREAM_EXCLUDE),
                "apiKey": api_key,
            },
            headers={"User-Agent": random.choice(USER_AGENTS)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for article in data.get("articles", []):
            title = (article.get("title") or "").strip()
            url = (article.get("url") or "").strip()
            if not title or not url or title == "[Removed]":
                continue

            description = article.get("description") or article.get("content") or ""
            words = description.split()

            published = datetime.now(timezone.utc)
            pub_str = article.get("publishedAt", "")
            if pub_str:
                try:
                    published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
            if age_hours > MAX_AGE_HOURS:
                continue

            items.append(ContentItem(
                title=title,
                url=url,
                source_name=article.get("source", {}).get("name", "NewsAPI"),
                source_tier="tier_3",
                published=published,
                summary=" ".join(words[:400]),
                word_count=len(words),
                position_tags=all_tags,
            ))
        return items
    except Exception:
        return []


def _fetch_gdelt(positions: list[dict]) -> list[ContentItem]:
    """
    GDELT Doc 2.0 API — free, no key, scans thousands of global outlets.
    Returns articles from last 24h matching position-tag themes.
    """
    if not positions:
        return []

    query, all_tags = _build_tag_query(positions, max_terms=5)
    if not query:
        return []

    try:
        time.sleep(random.uniform(0.5, 1.0))
        resp = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query + " sourcelang:english",
                "mode": "artlist",
                "maxrecords": 25,
                "format": "json",
                "timespan": "24h",
                "sort": "datedesc",
            },
            headers={"User-Agent": random.choice(USER_AGENTS)},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        items = []
        for art in data.get("articles", []):
            title = (art.get("title") or "").strip()
            url = (art.get("url") or "").strip()
            if not title or not url:
                continue

            # Skip mainstream domains
            domain = art.get("domain", "")
            if any(m in domain for m in MAINSTREAM_EXCLUDE):
                continue

            # Parse GDELT date format: "20240531120000"
            seendate = art.get("seendate", "")
            published = datetime.now(timezone.utc)
            if seendate and len(seendate) >= 14:
                try:
                    published = datetime.strptime(seendate[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            items.append(ContentItem(
                title=title,
                url=url,
                source_name=domain or "GDELT",
                source_tier="tier_3",
                published=published,
                summary=title,   # GDELT artlist has no body — title is all we get
                word_count=len(title.split()),
                position_tags=all_tags,
            ))
        return items
    except Exception:
        return []


def fetch_content(sources: dict, positions: list[dict] = None) -> list[ContentItem]:
    """
    Fetch all content sources and return flat ContentItem list.
    positions: list of position dicts from positions.yml — used for NewsAPI/GDELT queries.
    """
    all_items: list[ContentItem] = []

    # Tier 1 — Central banks
    for src in sources.get("central_banks", []):
        rss = src.get("rss") or src.get("url")
        if not rss:
            continue
        tags = src.get("position_tags", [])
        all_items.extend(_fetch_rss(rss, src["name"], "tier_1", tags))

    # Tier 2 — Buy-side
    for src in sources.get("buyside", []):
        freq = src.get("scrape_frequency", "daily")
        tags = src.get("position_tags", [])
        rss = src.get("rss")
        url = src.get("url")
        if rss:
            all_items.extend(_fetch_rss(rss, src["name"], "tier_2", tags))
        elif url and freq == "daily":
            all_items.extend(_scrape_html_links(url, src["name"], "tier_2", tags))

    # Tier 2 — Independent macro
    for src in sources.get("independent", []):
        rss = src.get("rss")
        tags = src.get("position_tags", [])
        if rss:
            all_items.extend(_fetch_rss(rss, src["name"], "tier_2", tags))

    # Tier 3 — Dynamic: NewsAPI keyword search
    if positions:
        import config as cfg
        all_items.extend(_fetch_newsapi(positions, cfg.NEWSAPI_KEY))

    # Tier 3 — Dynamic: GDELT broad sweep
    if positions:
        all_items.extend(_fetch_gdelt(positions))

    return all_items


def _scrape_html_links(url: str, source_name: str, source_tier: str, position_tags: list) -> list[ContentItem]:
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
