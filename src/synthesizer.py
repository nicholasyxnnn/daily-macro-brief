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
from typing import Optional
from src.content_scraper import ContentItem
from src.market_data import MarketDashboard
from src.calendar_scraper import CalendarData

_api_key = cfg.ANTHROPIC_API_KEY.strip()
if not _api_key:
    raise EnvironmentError(
        "ANTHROPIC_API_KEY is not set. Add it as a GitHub secret or export it locally."
    )

CLAUDE_MD = (Path(__file__).parent.parent / "CLAUDE.md").read_text()

client = anthropic.Anthropic(api_key=_api_key)

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


def _format_regime_context(items: list[ContentItem]) -> str:
    """Central bank items formatted as regime background — not Theme Radar candidates."""
    if not items:
        return "No central bank publications in the last 48h."
    return "\n".join(f"- [{item.source_name}] {item.title}" for item in items[:6])


def _format_news_context(items: list[ContentItem]) -> str:
    """Recent market news headlines for Module 2 context."""
    if not items:
        return "No recent market news available."
    return "\n".join(f"- [{item.source_name}] {item.title}" for item in items[:8])


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
    rules_chart_asset: str = "2s10s Spread",
    regime_items: list[ContentItem] = None,
    module2_news: list[ContentItem] = None,
    citation_item: Optional[ContentItem] = None,
) -> dict:
    """
    Single Sonnet call generating modules 2, 4 caption, 5, and 6.
    System prompt is prompt-cached for ~60-70% input cost reduction.
    """
    system_prompt = _build_system_prompt(positions)

    citation_block = ""
    if citation_item:
        citation_block = (
            f"\n\n## Contrarian Corner — Citation-Validated Signal\n"
            f"This piece was independently cited by {citation_item.citation_count} curated sources "
            f"but has not reached mainstream coverage. Consider it as one input for Module 6.\n"
            f"Title: {citation_item.title}\n"
            f"Source: {citation_item.source_name} | URL: {citation_item.url}\n"
            f"Excerpt: {citation_item.summary[:400]}"
        )

    user_content = (
        f"## Market Data (pre-fetched, do not modify numbers)\n"
        f"{market_data.format_telegram()}\n\n"
        f"## Calendar\n"
        f"{calendar_data.format_telegram()}\n\n"
        f"## Central Bank & Policy Backdrop (regime context)\n"
        f"{_format_regime_context(regime_items or [])}\n\n"
        f"## Current Market News (Module 2 context — what markets are reporting)\n"
        f"{_format_news_context(module2_news or [])}\n\n"
        f"## Chart Selection\n"
        f"Rules-based event trigger: {rules_chart_asset}\n"
        f"Available options: USD/JPY, Gold, US 10Y, 2s10s Spread, VIX, DXY, SPY, EM Debt\n\n"
        f"## Non-Mainstream Analytical Content (Modules 5 & 6 — Substacks + Exa discovery)\n"
        f"{_format_content_items(content_items)}"
        f"{citation_block}\n\n"
        f"## Task\n"
        f"You are a macro analyst writing for a PM who already reads Bloomberg, FT, and WSJ.\n"
        f"Synthesize, select, explain — state a point of view, never regurgitate.\n\n"
        f"  Module 2: Use market data + news context + calendar to identify the 3 things that "
        f"actually changed overnight and matter for this specific book. State the implication, "
        f"not the event. Numbers must come from market data above.\n"
        f"  Module 4: Select the single most insightful chart for today given the market context "
        f"and book. The rules-based trigger above fires on large moves — confirm it if correct, "
        f"or pick a different option if another chart tells a better story. On quiet days, choose "
        f"what best contextualizes the current macro regime for this book. "
        f"Write a caption ≤30 words: what it shows and why it matters now.\n"
        f"  Module 5: From the non-mainstream content above, select the 3 items with genuine "
        f"non-consensus signal for the book. Write the book implication from your own analytical "
        f"read — not a paraphrase of the source. Exa and Substack items are your primary material.\n"
        f"  Module 6: Identify a narrative the market is not pricing. Draw from the full data set: "
        f"overnight moves, calendar, content, and policy backdrop. If nothing explicit, derive it. "
        f"Never hedge. State a point of view.\n\n"
        f"Your entire response must be valid XML starting with <brief> and ending with </brief>.\n"
        f"Do not add any prose before or after the XML."
    )

    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=SONNET_MODEL,
                max_tokens=2500,
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
        except anthropic.APIStatusError as e:
            raise RuntimeError(
                f"{type(e).__name__} (status {e.status_code}): {e.message}"
            ) from e

    raw_xml = resp.content[0].text
    result = parse_synthesis(raw_xml)
    if not result:
        print(f"[WARN] parse_synthesis returned empty. Raw response (first 500 chars):\n{raw_xml[:500]}", flush=True)
    return result
