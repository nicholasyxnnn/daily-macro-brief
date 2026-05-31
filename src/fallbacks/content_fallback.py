"""
Content fallback: yesterday's unused high-scored items, cached to state/content_cache.json.
Last resort: central bank RSS only (most stable tier).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from src.content_scraper import ContentItem, fetch_content

CACHE_PATH = Path("state/content_cache.json")


def save_content_cache(items: list[ContentItem]) -> None:
    """Persist top scored items after a successful run for fallback use."""
    CACHE_PATH.parent.mkdir(exist_ok=True)
    payload = [
        {
            "title": it.title,
            "url": it.url,
            "source_name": it.source_name,
            "source_tier": it.source_tier,
            "published": it.published.isoformat(),
            "summary": it.summary,
            "word_count": it.word_count,
            "position_tags": it.position_tags,
            "score": it.score,
        }
        for it in items
    ]
    CACHE_PATH.write_text(json.dumps(payload))


def _load_cache() -> list[ContentItem]:
    if not CACHE_PATH.exists():
        return []
    try:
        payload = json.loads(CACHE_PATH.read_text())
        items = []
        for d in payload:
            items.append(ContentItem(
                title=d["title"],
                url=d["url"],
                source_name=d["source_name"],
                source_tier=d["source_tier"],
                published=datetime.fromisoformat(d["published"]),
                summary=d["summary"],
                word_count=d["word_count"],
                position_tags=d.get("position_tags", []),
                score=d.get("score", 0.0),
            ))
        return items
    except Exception:
        return []


def get_content_fallback(sources: dict = None) -> list[ContentItem]:
    """Return cached items from yesterday, or fall back to central bank RSS only."""
    cached = _load_cache()
    if cached:
        return cached[:3]

    # Last resort: central bank RSS (tier_1, most reliable)
    if sources:
        cb_sources = {"central_banks": sources.get("central_banks", []),
                      "buyside": [], "independent": [], "twitter": []}
        try:
            items = fetch_content(cb_sources)
            return items[:3]
        except Exception:
            pass

    return []
