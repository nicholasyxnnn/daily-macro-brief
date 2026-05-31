"""
Module 4 — Dynamic chart selection and generation.
Selection is rules-based (no LLM). LLM writes the caption only.
"""
from __future__ import annotations
import io
from datetime import datetime, timedelta
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import yfinance as yf

from src.market_data import MarketDashboard

# Ticker map for chart generation (name → yfinance symbol)
CHART_TICKERS: dict[str, str] = {
    "USD/JPY":  "JPY=X",
    "Gold":     "GC=F",
    "EM Debt":  "EMB",       # iShares EM Bond ETF as proxy
    "US 10Y":   "^TNX",
    "SPY":      "SPY",
    "VIX":      "^VIX",
    "DXY":      "DX-Y.NYB",
    "2s10s":    None,        # computed from TNX + DGS2
}

STD_DEV_WINDOW = 60  # days for overnight std dev calculation


def _overnight_std_devs(name: str, raw: dict) -> float:
    """Estimate how many std devs last night's move was, using 60-day rolling."""
    ticker_sym = CHART_TICKERS.get(name)
    if not ticker_sym:
        return 0.0
    try:
        hist = yf.Ticker(ticker_sym).history(period=f"{STD_DEV_WINDOW + 5}d")["Close"].dropna()
        if len(hist) < 10:
            return 0.0
        daily_chg = hist.pct_change().dropna()
        std = float(daily_chg.std())
        last_chg = float(daily_chg.iloc[-1])
        return abs(last_chg / std) if std > 0 else 0.0
    except Exception:
        return 0.0


def select_chart(
    market_data: MarketDashboard,
    positions: list[dict],
) -> tuple[str, Optional[str], int]:
    """
    Returns (asset_name, yfinance_ticker, lookback_days).

    Priority:
    1. Position-tagged asset moved >1.5 std dev overnight
    2. Yield curve moved significantly (|2s10s change| > 5bp)
    3. VIX spike (>15% intraday)
    4. EM stress (DXY move >0.8%)
    5. Default: yield curve 6-month lookback
    """
    position_names = {p["asset"].split()[0] for p in positions}  # rough match

    # 1. Position-tagged asset that moved significantly
    candidates = [
        ("USD/JPY", "JPY=X", 90),
        ("Gold",    "GC=F",  90),
        ("SPY",     "SPY",   90),
    ]
    for name, sym, lookback in candidates:
        if name in position_names or any(name in p["asset"] for p in positions):
            std_devs = _overnight_std_devs(name, market_data.raw)
            if std_devs >= 1.5:
                return name, sym, lookback

    # 2. Yield curve move
    if abs(market_data.spread_change_bp) > 5:
        return "2s10s Spread", "^TNX", 180

    # 3. VIX spike
    vix_now = market_data.raw.get("VIX", 0)
    vix_prev = market_data.raw.get("VIX_prev", vix_now)
    if vix_prev and vix_now / vix_prev - 1 > 0.15:
        return "VIX", "^VIX", 30

    # 4. EM stress: DXY large move
    dxy_row = next((r for r in market_data.fx if r.name == "DXY"), None)
    if dxy_row and abs(dxy_row.pct_change or 0) > 0.8:
        return "DXY", "DX-Y.NYB", 90

    # 5. Default
    return "2s10s Spread", "^TNX", 180


def generate_chart(asset_name: str, ticker: Optional[str], lookback_days: int = 90) -> bytes:
    """
    Generates a Bloomberg-aesthetic line chart and returns PNG bytes.
    For 2s10s spread, fetches TNX and computes spread via FRED.
    """
    end = datetime.today()
    start = end - timedelta(days=lookback_days + 10)

    if asset_name == "2s10s Spread":
        series = _fetch_2s10s_spread(start, end)
        ylabel = "Spread (bp)"
        title = "US 2s10s Treasury Spread"
    else:
        hist = yf.Ticker(ticker).history(start=start, end=end)
        series = hist["Close"].dropna()
        ylabel = "Price"
        title = asset_name

    series = series.iloc[-lookback_days:]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    color = "#00d4aa"
    ax.plot(series.index, series.values, color=color, linewidth=1.5)
    ax.fill_between(series.index, series.values, series.values.min(), alpha=0.15, color=color)

    # Axes styling
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.tick_params(colors="#8b949e", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)

    ax.yaxis.tick_right()
    ax.set_ylabel(ylabel, color="#8b949e", fontsize=8)
    ax.yaxis.set_label_position("right")
    ax.set_title(title, color="#e6edf3", fontsize=10, pad=10)
    ax.grid(axis="y", color="#21262d", linewidth=0.5)

    # Mark last value
    last_val = float(series.iloc[-1])
    ax.annotate(
        f"{last_val:.2f}",
        xy=(series.index[-1], last_val),
        xytext=(5, 0),
        textcoords="offset points",
        color=color,
        fontsize=9,
        fontweight="bold",
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fetch_2s10s_spread(start: datetime, end: datetime):
    """Fetch US 2s10s spread via FRED API and return as pandas Series in bp."""
    import config as cfg
    from fredapi import Fred
    import pandas as pd

    fred = Fred(api_key=cfg.FRED_API_KEY)
    y2 = fred.get_series("DGS2", observation_start=start, observation_end=end).dropna()
    y10 = fred.get_series("DGS10", observation_start=start, observation_end=end).dropna()
    spread = (y10 - y2) * 100  # bp
    spread = spread.dropna()
    spread.index = pd.to_datetime(spread.index)
    return spread
