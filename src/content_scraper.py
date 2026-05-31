"""
Module 5 data layer — Three-layer content sourcing.

Layer 1: Curated registry — central bank RSS + trusted Substacks (always runs)
Layer 2: Exa.ai semantic discovery — queries driven by overnight market movers
Layer 3: Citation tracking — surfaces cross-cited non-mainstream pieces for Contrarian Corner
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import Optional
from urllib.parse import urljoin, urlparse
import calendar as _calendar
import random
import time
import feedparser
import requests
from bs4 import BeautifulSoup

import config as cfg

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

MAX_AGE_HOURS = 48

MAINSTREAM_EXCLUDE = [
    "bloomberg.com", "reuters.com", "ft.com", "wsj.com",
    "cnbc.com", "businessinsider.com", "marketwatch.com",
    "economist.com", "nytimes.com", "theguardian.com",
]


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
    citation_count: int = 0  # Layer 3: # of Layer 1 sources that linked this URL


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return datetime.fromtimestamp(_calendar.timegm(t), tz=timezone.utc)
    return None


def _entry_to_item(
    entry, source_name: str, source_tier: str, position_tags: list
) -> Optional[ContentItem]:
    title = getattr(entry, "title", "").strip()
    url = getattr(entry, "link", "").strip()
    if not title or not url:
        return None

    published = _parse_date(entry) or datetime.now(timezone.utc)
    if (datetime.now(timezone.utc) - published).total_seconds() / 3600 > MAX_AGE_HOURS:
        return None

    raw = getattr(entry, "summary", "") or ""
    if not raw:
        content = getattr(entry, "content", [])
        if content:
            raw = content[0].get("value", "")
    if raw:
        raw = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
    words = raw.split()

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


def _fetch_rss(
    url: str, source_name: str, source_tier: str, position_tags: list
) -> list[ContentItem]:
    try:
        time.sleep(random.uniform(0.3, 0.8))
        feed = feedparser.parse(url, request_headers=_random_headers())
        return [
            item for entry in feed.entries
            if (item := _entry_to_item(entry, source_name, source_tier, position_tags))
        ]
    except Exception:
        return []


# ── Layer 1: Curated Registry ─────────────────────────────────────────────────

def _fetch_layer1(sources: dict) -> list[ContentItem]:
    """Central bank RSS feeds + trusted Substacks. Always runs, guaranteed content."""
    items: list[ContentItem] = []
    for src in sources.get("central_banks", []):
        if rss := src.get("rss"):
            items.extend(_fetch_rss(rss, src["name"], "tier_1", src.get("position_tags", [])))
    for src in sources.get("independent", []):
        if rss := src.get("rss"):
            items.extend(_fetch_rss(rss, src["name"], "tier_2", src.get("position_tags", [])))
    return items


# ── Layer 2: Exa Semantic Discovery ──────────────────────────────────────────

def _extract_top_movers(market_data) -> list[dict]:
    """Top 3 assets by absolute overnight move from MarketDashboard."""
    movers = []
    for asset in (
        market_data.us_equities + market_data.eu_equities +
        market_data.fx + market_data.commodities + market_data.crypto
    ):
        if asset.pct_change is not None:
            movers.append({"name": asset.name, "pct_change": asset.pct_change})
    for rate in market_data.rates:
        if rate.bp_change is not None:
            movers.append({"name": rate.name, "bp_change": rate.bp_change})
    movers.sort(
        key=lambda x: abs(x.get("pct_change") or x.get("bp_change", 0) / 100),
        reverse=True,
    )
    return movers[:3]


def _detect_regime(market_data) -> str:
    """Characterize the current macro regime from market data for query framing."""
    signals = []

    vix = market_data.raw.get("VIX")
    if vix:
        if vix > 25:
            signals.append("elevated volatility / risk-off")
        elif vix < 15:
            signals.append("suppressed volatility / potential complacency")

    spread = market_data.spread_2s10s
    if spread < -30:
        signals.append("inverted yield curve")
    elif spread > 50:
        signals.append("steepening yield curve")

    for asset in market_data.fx:
        if "EUR" in asset.name and asset.pct_change is not None:
            if asset.pct_change < -0.5:
                signals.append("dollar strengthening")
            elif asset.pct_change > 0.5:
                signals.append("dollar weakening")
            break

    sp = next((a for a in market_data.us_equities if "S&P" in a.name), None)
    if sp and sp.pct_change is not None:
        if sp.pct_change < -1.5:
            signals.append("equity risk-off")
        elif sp.pct_change > 1.5:
            signals.append("equity risk-on")

    return ", ".join(signals) if signals else "mixed macro signals"


def _build_exa_queries(market_data, positions: list[dict]) -> list[str]:
    """
    Build 3 targeted semantic queries — framed like an institutional macro analyst
    asking what the market is missing, not what happened.
    """
    movers = _extract_top_movers(market_data)
    regime = _detect_regime(market_data)
    themes = list(dict.fromkeys(tag for p in positions for tag in p.get("tags", [])))[:6]
    queries = []

    # Q1: Non-consensus explanation of the top overnight mover
    if movers:
        top = movers[0]
        if (pct := top.get("pct_change")) is not None:
            direction = "higher" if pct > 0 else "lower"
            queries.append(
                f"Why {top['name']} is {abs(pct):.1f}% {direction} — "
                f"independent analytical view challenging the consensus explanation. "
                f"Non-mainstream macro research, not news coverage."
            )
        elif (bp := top.get("bp_change")) is not None:
            direction = "higher" if bp > 0 else "lower"
            queries.append(
                f"Why {top['name']} moved {abs(bp):.0f}bp {direction} — "
                f"non-consensus structural view on what is driving this. "
                f"Independent macro analysis, not news."
            )

    # Q2: What consensus is missing on high-conviction active positions
    high_conviction = [p for p in positions if p.get("conviction") == "high"]
    if high_conviction:
        pos_desc = "; ".join(f"{p['asset']} ({p['theme']})" for p in high_conviction[:2])
        queries.append(
            f"Independent research on risks or non-consensus views for: {pos_desc}. "
            f"What is institutional consensus positioning getting wrong? "
            f"Analytical content, not headlines."
        )
    elif themes:
        queries.append(
            f"Non-consensus macro research on: {', '.join(themes[:4])}. "
            f"What is the market not pricing? Independent analytical perspective."
        )

    # Q3: Tail risks and ignored narratives given current macro regime
    queries.append(
        f"Underpriced macro tail risks and ignored narratives given {regime}. "
        f"What are institutional investors not positioned for? "
        f"Themes: {', '.join(themes[:4])}. Non-mainstream research or Substack analysis."
    )

    return queries


def _fetch_layer2_exa(
    market_data, positions: list[dict], api_key: str
) -> list[ContentItem]:
    """
    Layer 2: Three targeted Exa neural searches.
    Queries are regime-aware and framed around what the market is missing,
    not what price moved — dynamic source discovery, not keyword matching.
    """
    if not api_key or market_data is None:
        return []
    try:
        from exa_py import Exa
    except ImportError:
        return []

    queries = _build_exa_queries(market_data, positions)
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_tags = list(dict.fromkeys(tag for p in positions for tag in p.get("tags", [])))

    seen_urls: set[str] = set()
    items: list[ContentItem] = []

    try:
        exa = Exa(api_key=api_key)
        for query in queries:
            try:
                results = exa.search_and_contents(
                    query,
                    type="neural",
                    num_results=5,
                    start_published_date=since,
                    text=True,
                    highlights=True,
                    exclude_domains=MAINSTREAM_EXCLUDE,
                )
            except Exception:
                continue

            for r in results.results:
                title = (getattr(r, "title", None) or "").strip()
                url = (getattr(r, "url", None) or "").strip()
                if not title or not url or url in seen_urls:
                    continue
                if any(m in url for m in MAINSTREAM_EXCLUDE):
                    continue
                seen_urls.add(url)

                published = datetime.now(timezone.utc)
                pub_date = getattr(r, "published_date", None)
                if pub_date:
                    try:
                        published = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                raw_highlights = getattr(r, "highlights", None)
                raw_text = getattr(r, "text", None)
                if raw_highlights and isinstance(raw_highlights, list):
                    summary = " ".join(str(h) for h in raw_highlights)
                elif raw_text:
                    summary = str(raw_text)[:1600]
                else:
                    summary = ""
                words = summary.split()

                items.append(ContentItem(
                    title=title,
                    url=url,
                    source_name=urlparse(url).netloc.replace("www.", ""),
                    source_tier="tier_2",
                    published=published,
                    summary=" ".join(words[:400]),
                    word_count=len(words),
                    position_tags=all_tags,
                ))
    except Exception:
        return []

    return items


# ── Layer 3: Citation Tracking ────────────────────────────────────────────────

def _fetch_outbound_links(url: str) -> list[str]:
    """Fetch an article, return non-mainstream outbound links."""
    try:
        time.sleep(random.uniform(0.3, 0.7))
        resp = requests.get(url, headers=_random_headers(), timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        base_domain = urlparse(url).netloc
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = urljoin(url, href)
            domain = urlparse(href).netloc
            if domain and domain != base_domain and not any(m in domain for m in MAINSTREAM_EXCLUDE):
                links.append(href)
        return links
    except Exception:
        return []


def _fetch_layer3_citations(
    layer1_items: list[ContentItem], positions: list[dict]
) -> list[ContentItem]:
    """
    Count how many Layer 1 articles link to the same external URL.
    URLs cited by 2+ independent sources surface as Contrarian Corner candidates.
    """
    citation_counts: Counter = Counter()
    for item in layer1_items[:12]:
        for link in _fetch_outbound_links(item.url):
            p = urlparse(link)
            normalized = f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
            citation_counts[normalized] += 1

    cross_cited = sorted(
        ((url, n) for url, n in citation_counts.items() if n >= 2),
        key=lambda x: x[1], reverse=True,
    )

    all_tags = list(dict.fromkeys(tag for p in positions for tag in p.get("tags", [])))
    items: list[ContentItem] = []
    for cited_url, count in cross_cited[:3]:
        try:
            time.sleep(random.uniform(0.4, 0.9))
            resp = requests.get(cited_url, headers=_random_headers(), timeout=12)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else ""
            if not title:
                og = soup.find("meta", property="og:title")
                title = og.get("content", "").strip() if og else cited_url

            body = " ".join(
                p_tag.get_text(strip=True) for p_tag in soup.find_all("p")
                if len(p_tag.get_text(strip=True)) > 40
            )
            words = body.split()

            items.append(ContentItem(
                title=title,
                url=cited_url,
                source_name=urlparse(cited_url).netloc.replace("www.", ""),
                source_tier="tier_2",
                published=datetime.now(timezone.utc),
                summary=" ".join(words[:400]),
                word_count=len(words),
                position_tags=all_tags,
                citation_count=count,
            ))
        except Exception:
            continue
    return items


# ── NewsAPI — Module 2 context ────────────────────────────────────────────────

def _fetch_newsapi(positions: list[dict], api_key: str) -> list[ContentItem]:
    """
    NewsAPI search for recent market-relevant news.
    Tagged source_tier='news' — used as Module 2 context only, not Theme Radar.
    Mainstream sources included intentionally: Module 2 needs to know what happened.
    """
    if not api_key or not positions:
        return []

    assets = [p.get("asset", "") for p in positions if p.get("asset")][:4]
    query = " OR ".join(f'"{a}"' if " " in a else a for a in assets) if assets else "macro markets"

    from datetime import date, timedelta as _td
    yesterday = (date.today() - _td(days=1)).isoformat()

    try:
        time.sleep(random.uniform(0.5, 1.0))
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": yesterday,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 10,
                "apiKey": api_key,
            },
            headers={"User-Agent": random.choice(USER_AGENTS)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items: list[ContentItem] = []
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

            if (datetime.now(timezone.utc) - published).total_seconds() / 3600 > MAX_AGE_HOURS:
                continue

            items.append(ContentItem(
                title=title,
                url=url,
                source_name=article.get("source", {}).get("name", "NewsAPI"),
                source_tier="news",
                published=published,
                summary=" ".join(words[:200]),
                word_count=len(words),
                position_tags=[],
            ))
        return items[:8]
    except Exception:
        return []


# ── Entry point ───────────────────────────────────────────────────────────────

def fetch_content(
    sources: dict,
    positions: list[dict] = None,
    market_data=None,
) -> list[ContentItem]:
    """
    Three-layer content fetch + NewsAPI for Module 2 context.
    Layer 1 always runs. Layer 2 requires EXA_API_KEY + market_data.
    Layer 3 runs after Layer 1 with no additional config required.
    NewsAPI items tagged 'news' route to Module 2 context only.
    """
    positions = positions or []
    layer1 = _fetch_layer1(sources)
    layer2 = _fetch_layer2_exa(market_data, positions, cfg.EXA_API_KEY)
    layer3 = _fetch_layer3_citations(layer1, positions)
    news = _fetch_newsapi(positions, cfg.NEWSAPI_KEY)

    print(
        f"[content] L1={len(layer1)} L2_exa={len(layer2)} L3_cite={len(layer3)} news={len(news)}",
        flush=True,
    )
    return layer1 + layer2 + layer3 + news
