"""
Orchestrator — wires all modules together.
Each module runs in isolated try/except; one failure cannot cascade.
State file prevents duplicate briefs on retry runs (idempotency).
"""
import datetime
import json
import sys
import traceback
from pathlib import Path

import config as cfg
from src.market_data import fetch_market_data
from src.calendar_scraper import fetch_calendar
from src.content_scraper import fetch_content
from src.scorer import score_and_rank
from src.synthesizer import haiku_prefilter, synthesize
from src.chart import select_chart, generate_chart
from src.delivery import (
    send_module, send_chart,
    format_module_2, format_module_5, format_module_6,
    send_incomplete_notice,
)
from src.fallbacks.market_fallback import get_market_fallback, save_market_cache
from src.fallbacks.calendar_fallback import get_calendar_fallback
from src.fallbacks.content_fallback import get_content_fallback, save_content_cache
from src.validators.scrape_validator import validate_market_data, validate_content_items
from src.validators.output_validator import validate_output
from src.monitoring.admin_alerts import admin_alert

STATE_PATH = Path("state/run_state.json")


def _is_already_run() -> bool:
    if not STATE_PATH.exists():
        return False
    try:
        state = json.loads(STATE_PATH.read_text())
        today = datetime.date.today().isoformat()
        return state.get("last_run") == today and state.get("status") == "success"
    except Exception:
        return False


def _mark_success() -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "last_run": datetime.date.today().isoformat(),
        "status": "success",
    }))


def main() -> None:
    if _is_already_run():
        print("Already ran successfully today. Exiting.")
        return

    positions = cfg.load_positions()
    sources = cfg.load_sources()
    active_positions = positions.get("positions", [])

    # ── Module 1: Market Data ──────────────────────────────────────────────
    try:
        market_data = fetch_market_data()
        validate_market_data(market_data)
        save_market_cache(market_data)
    except Exception as e:
        admin_alert("market_data", e)
        market_data = get_market_fallback()

    # ── Module 3: Calendar ────────────────────────────────────────────────
    try:
        calendar_data = fetch_calendar()
    except Exception as e:
        admin_alert("calendar", e)
        calendar_data = get_calendar_fallback()

    # ── Module 5 data: Content scrape + score + prefilter ─────────────────
    citation_item = None
    regime_items = []
    try:
        raw_items = fetch_content(sources, active_positions, market_data)
        valid_items = validate_content_items(raw_items)

        # Separate by role:
        # tier_1 (central banks) → regime context for all modules
        # tier_2 (Substacks + Exa) → Theme Radar candidates (non-mainstream signal)
        # citation_count >= 2 → Contrarian Corner feed
        regime_items = [i for i in valid_items if i.source_tier == "tier_1"]
        citation_items = [i for i in valid_items if i.citation_count >= 2]
        citation_item = max(citation_items, key=lambda x: x.citation_count, default=None)

        theme_candidates = [
            i for i in valid_items
            if i.source_tier != "tier_1" and i.citation_count == 0
        ]
        scored_items = score_and_rank(theme_candidates, active_positions)

        # Haiku prefilter: approve/reject from top scored items, always deliver 3
        approved, rejected = [], []
        for it in scored_items[:6]:
            (approved if haiku_prefilter(it) else rejected).append(it)
        # Fill to 3: approved first, then rejected as backfill
        content_items = (approved + rejected)[:3]
        if not content_items:
            content_items = scored_items[:3]
        save_content_cache(scored_items[:10])
    except Exception as e:
        admin_alert("content", e)
        content_items = get_content_fallback(sources)

    # ── Module 4: Chart selection ──────────────────────────────────────────
    chart_bytes = None
    chart_caption = ""
    try:
        chart_asset, chart_ticker, lookback = select_chart(market_data, active_positions)
        chart_bytes = generate_chart(chart_asset, chart_ticker, lookback)
    except Exception as e:
        admin_alert("chart", e)
        chart_asset = "yield curve"

    # ── Synthesis: single Claude call for modules 2, 4 caption, 5, 6 ──────
    try:
        synthesis = synthesize(
            market_data=market_data,
            calendar_data=calendar_data,
            content_items=content_items,
            regime_items=regime_items,
            positions=positions,
            chart_asset=chart_asset,
            citation_item=citation_item,
        )
        synthesis = validate_output(synthesis)
        chart_caption = synthesis.get("module_4_caption", "")
    except Exception as e:
        admin_alert("synthesis", e)
        print(f"Synthesis failed: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    # ── Delivery: one section at a time ───────────────────────────────────
    modules_sent: list[int] = []
    try:
        send_module("OVERNIGHT DASHBOARD", market_data.format_telegram())
        modules_sent.append(1)

        send_module("3 THINGS THAT MATTER TODAY", format_module_2(synthesis["module_2"]))
        modules_sent.append(2)

        send_module("TODAY'S CALENDAR", calendar_data.format_telegram())
        modules_sent.append(3)

        if chart_bytes:
            send_chart(chart_bytes, chart_caption)
        else:
            send_module("CHART", "[Chart generation failed — admin notified]")
        modules_sent.append(4)

        send_module("THEME RADAR", format_module_5(synthesis["module_5"]))
        modules_sent.append(5)

        send_module("CONTRARIAN CORNER", format_module_6(synthesis["module_6"]))
        modules_sent.append(6)

        _mark_success()

    except Exception as e:
        admin_alert("delivery", e)
        missing = [m for m in [1, 2, 3, 4, 5, 6] if m not in modules_sent]
        if missing:
            send_incomplete_notice(missing)
        sys.exit(1)


if __name__ == "__main__":
    main()
