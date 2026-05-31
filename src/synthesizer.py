"""
Claude API integration.
- Haiku pre-filter: binary substance check on top scored items (~50 tokens/call)
- Sonnet synthesis: single call for all modules, prompt-cached system prompt
"""
from pathlib import Path
import time
import anthropic
import config as cfg
from prompts.schemas import OUTPUT_SCHEMA, parse_synthesis
from src.content_scraper import ContentItem
from src.market_data import MarketDashboard
from src.calendar_scraper import CalendarData

if not cfg.ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "ANTHROPIC_API_KEY is not set. Add it as a GitHub secret or export it locally."
    )

CLAUDE_MD = (Path(__file__).parent.parent / "CLAUDE.md").read_text()

client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"


def haiku_prefilter(item: ContentItem) -> bool:
    """Returns True if item is analytically substantive for a macro investor."""
    text = f"{item.title}\n\n{item.summary[:400]}"
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": (
                    "Is the following content analytically substantive for an "
                    "institutional macro investor? Answer only YES or NO.\n\n" + text
                ),
            }],
        )
        return resp.content[0].text.strip().upper().startswith("YES")
    except Exception:
        return True  # fail open — don't drop items on API error


def _format_positions(positions: dict) -> str:
    lines = ["## Current Book"]
    for p in positions.get("positions", []):
        lines.append(
            f"- {p['asset']}: {p['direction'].upper()} | conviction={p['conviction']} | "
            f"theme: {p['theme']} | tags: {', '.join(p['tags'])}"
        )
    lines.append("\n## Watching")
    for w in positions.get("watching", []):
        lines.append(f"- {w['theme']} | tags: {', '.join(w['tags'])}")
    return "\n".join(lines)


def _format_content_items(items: list[ContentItem]) -> str:
    parts = []
    for i, item in enumerate(items, 1):
        parts.append(
            f"[CONTENT {i}]\n"
            f"Title: {item.title}\n"
            f"Source: {item.source_name} ({item.source_tier})\n"
            f"URL: {item.url}\n"
            f"Excerpt: {item.summary[:400]}"
        )
    return "\n\n".join(parts)


def _build_system_prompt(positions: dict) -> str:
    return (
        CLAUDE_MD
        + "\n\n"
        + _format_positions(positions)
        + "\n\n## Output Schema\nPopulate every tag. No additions. No omissions.\n"
        + OUTPUT_SCHEMA
    )


def synthesize(
    market_data: MarketDashboard,
    calendar_data: CalendarData,
    content_items: list[ContentItem],
    positions: dict,
    chart_asset: str,
) -> dict:
    """
    Single Sonnet call generating modules 2, 4 caption, 5, and 6.
    System prompt is prompt-cached for ~60-70% input cost reduction.
    """
    system_prompt = _build_system_prompt(positions)

    user_content = (
        f"## Market Data (pre-fetched, do not modify numbers)\n"
        f"{market_data.format_telegram()}\n\n"
        f"## Calendar\n"
        f"{calendar_data.format_telegram()}\n\n"
        f"## Chart Selected\n"
        f"Asset: {chart_asset} (rules-based selection, already determined)\n\n"
        f"## Content Items for Theme Radar\n"
        f"{_format_content_items(content_items)}\n\n"
        f"## Task\n"
        f"Produce the XML brief. Modules 2, 4, 5, and 6 only. "
        f"Numbers in module 2 must reference the market data above. "
        f"Never invent prices or rates."
    )

    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1200,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except anthropic.APIConnectionError:
            if attempt == 0:
                time.sleep(10)
                continue
            raise

    raw_xml = resp.content[0].text
    return parse_synthesis(raw_xml)
