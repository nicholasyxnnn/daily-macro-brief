"""
Relevance scoring — pure Python, zero token cost.
Runs before any LLM call to rank content items by signal value to the PM.
"""
from datetime import datetime, timezone
from src.content_scraper import ContentItem


def get_all_position_tags(positions: list[dict]) -> set[str]:
    tags = set()
    for p in positions:
        tags.update(p.get("tags", []))
    return tags


def score_content(item: ContentItem, positions: list[dict]) -> float:
    score = 0.0
    now = datetime.now(timezone.utc)

    # Recency: published within last 24h = max bonus, decays linearly
    hours_old = (now - item.published).total_seconds() / 3600
    score += max(0.0, 10.0 - hours_old * 0.4)

    # Position tag match
    all_tags = get_all_position_tags(positions)
    matched_tags = set(item.position_tags) & all_tags
    score += len(matched_tags) * 3

    # Conviction weight: high-conviction positions score higher
    conviction_bonus = {"high": 3, "medium": 2, "low": 1}
    for position in positions:
        if any(tag in item.position_tags for tag in position.get("tags", [])):
            score += conviction_bonus.get(position.get("conviction", ""), 0)

    # Substance filter: thin posts penalized
    if item.word_count < 300:
        score -= 5

    # Source tier bonus — tier_2 (Substacks, Exa) scores higher than tier_1 (central banks)
    # for the non-mainstream mandate: central banks are mainstream by definition for a macro PM
    tier_bonus = {"tier_1": 2, "tier_2": 4}
    score += tier_bonus.get(item.source_tier, 0)

    return score


def score_and_rank(items: list[ContentItem], positions: list[dict]) -> list[ContentItem]:
    """Score all items, attach score, return sorted descending."""
    for item in items:
        item.score = score_content(item, positions)
    return sorted(items, key=lambda x: x.score, reverse=True)
