"""
Market data fallback chain:
1. Alpha Vantage API (ALPHA_VANTAGE_KEY env var, optional)
2. Previous day's cached data from state/market_cache.json with [STALE] flag
"""
import json
import os
from datetime import date
from pathlib import Path

from src.market_data import MarketDashboard, AssetRow

CACHE_PATH = Path("state/market_cache.json")


def save_market_cache(dashboard: MarketDashboard) -> None:
    """Called by main.py on successful fetch to persist today's data."""
    CACHE_PATH.parent.mkdir(exist_ok=True)
    payload = {
        "as_of": dashboard.as_of,
        "raw": dashboard.raw,
        "telegram_text": dashboard.format_telegram(),
    }
    CACHE_PATH.write_text(json.dumps(payload))


def get_market_fallback() -> MarketDashboard:
    """Return stale cached data with [STALE] flag, or a minimal placeholder."""
    if CACHE_PATH.exists():
        try:
            payload = json.loads(CACHE_PATH.read_text())
            stale_date = payload.get("as_of", "unknown")
            # Wrap cached telegram text with stale flag
            cached_text = payload.get("telegram_text", "")
            stale_label = f"\n<b>[STALE DATA — as of {stale_date}]</b>"

            # Build a minimal MarketDashboard that returns the cached + stale text
            class StaleDashboard(MarketDashboard):
                def format_telegram(self) -> str:
                    return cached_text + stale_label

            return StaleDashboard(
                as_of=stale_date,
                equities=[],
                rates=[],
                fx=[],
                commodities=[],
                crypto=[],
                spread_2s10s=0.0,
                spread_change_bp=0.0,
                raw=payload.get("raw", {}),
            )
        except Exception:
            pass

    # Minimal placeholder if no cache exists
    class PlaceholderDashboard(MarketDashboard):
        def format_telegram(self) -> str:
            return "<b>[MARKET DATA UNAVAILABLE — fetch failed, no cache]</b>"

    return PlaceholderDashboard(
        as_of=date.today().isoformat(),
        equities=[], rates=[], fx=[], commodities=[], crypto=[],
        spread_2s10s=0.0, spread_change_bp=0.0, raw={},
    )
