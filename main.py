"""
Orchestrator — wires all modules together.
Each module runs in isolated try/except; one failure cannot cascade.
State file prevents duplicate briefs on retry runs (idempotency).
"""
import datetime
import json
import sys
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
    try:
        raw_items = fetch_content(sources)
        valid_items = validate_content_items(raw_items)
        scored_items = score_and_rank(valid_items, active_positions)

        # Haiku prefilter runs on top 3 only
        top3 = scored_items[:3]
        filtered = [it for it in top3 if haiku_prefilter(it)]
        content_items = filtered if filtered else top3  # fail open
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
            positions=positions,
            chart_asset=chart_asset,
        )
        synthesis = validate_output(synthesis)
        chart_caption = synthesis.get("module_4_caption", "")
    except Exception as e:
        admin_alert("synthesis", e)
        print(f"Synthesis failed: {e}", file=sys.stderr)
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
