"""
Module 4 — Chart selection and generation.

Editorial philosophy: the chart should surface something the PM didn't already
know to look for. Selection priority is driven by ContentSignal (what the LLM
found editorially interesting in today's scraped content), not by overnight price
moves. Price-move rules exist only as fallback when no content signal is strong
enough to override.

The LLM in synthesizer.py picks the final chart from get_chart_menu(); this
module executes that pick and falls back through the priority stack if the pick
is invalid or absent.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import yfinance as yf

import config as cfg
from src.market_data import MarketDashboard

# name → (yfinance_ticker | None, lookback_days, description_for_llm)
# None ticker = FRED series or computed ratio — dispatched by name in generate_chart
CHART_OPTIONS: dict[str, tuple[Optional[str], int, str]] = {
    "USD/JPY":           ("JPY=X",      90,  "USD/JPY spot — BoJ normalization vs Fed divergence; key for long USDJPY position"),
    "Gold":              ("GC=F",       90,  "Gold spot — real rate sensitivity, EM reserve diversification, de-dollarization flows"),
    "US 10Y":            ("^TNX",       180, "US 10yr Treasury yield — duration risk benchmark, Fed expectations anchor"),
    "2s10s Spread":      (None,         180, "US yield curve slope (bp) — recession signal, steepener position context"),
    "VIX":               ("^VIX",       30,  "Equity implied vol — risk-off gauge, tail hedge pricing"),
    "DXY":               ("DX-Y.NYB",   90,  "USD index — broad dollar strength, EM stress and carry viability"),
    "SPY":               ("SPY",        90,  "S&P 500 — US equity regime, risk-on/risk-off backdrop"),
    "EM Debt":           ("EMB",        90,  "EM hard currency sovereign debt ETF — EM credit spreads and flows"),
    "Real Yield US 10Y": (None,         180, "US 10yr real yield (TIPS-implied) — true tightening signal, gold headwind/tailwind"),
    "USD EM FX":         ("CEW",        90,  "EM currency basket ETF — EM FX stress, carry basket viability"),
    "Oil/Gold Ratio":    (None,         180, "Brent/Gold ratio — growth vs haven demand balance, inflation regime signal"),
    "Copper/Gold Ratio": (None,         90,  "Copper/Gold ratio — industrial demand vs haven; China proxy, global growth signal"),
    "US Financial Cond": (None,         90,  "Chicago Fed NFCI — credit and funding conditions tightness"),
    "Fed Funds Futures": (None,         90,  "Fed Funds target median (FRED) — market-implied rate path"),
}

ROTATING_DEFAULTS = [
    "2s10s Spread",
    "Real Yield US 10Y",
    "Copper/Gold Ratio",
    "Oil/Gold Ratio",
]

STD_DEV_WINDOW = 60


@dataclass
class ContentSignal:
    source: str
    credibility: str       # "tier_1" | "tier_2"
    summary: str
    suggested_chart: str   # name from CHART_OPTIONS, or ""
    novelty_score: float   # 0.0–1.0


def get_chart_menu() -> dict[str, str]:
    """Return {name: description} for all chart options. Passed to the LLM — no tickers."""
    return {name: opts[2] for name, opts in CHART_OPTIONS.items()}


def resolve_chart(
    claude_pick: str,
    rules_asset: str,
    rules_ticker: Optional[str],
    rules_lookback: int,
) -> tuple[str, Optional[str], int]:
    """Use Claude's chart pick if valid; fall back to rules-based selection."""
    if claude_pick and claude_pick in CHART_OPTIONS:
        ticker, lookback, _ = CHART_OPTIONS[claude_pick]
        return claude_pick, ticker, lookback
    return rules_asset, rules_ticker, rules_lookback


def _overnight_std_devs(name: str) -> float:
    ticker_sym = CHART_OPTIONS.get(name, (None,))[0]
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
    content_signals: list[ContentSignal],
    market_data: MarketDashboard,
    positions: list[dict],
) -> tuple[str, Optional[str], int]:
    """
    Returns (asset_name, yfinance_ticker_or_None, lookback_days).

    Priority:
    0. tier_1 ContentSignal with novelty > 0.7 and valid suggested_chart
    1. tier_2 ContentSignal with novelty > 0.8 and valid suggested_chart
    2. Position-tagged asset moved >1.5 std devs overnight
    3. |2s10s change| > 5bp
    4. VIX spike >15%
    5. DXY move >0.8%
    6. Rotating default by day-of-week
    """
    def _resolve(name: str) -> tuple[str, Optional[str], int]:
        ticker, lookback, _ = CHART_OPTIONS[name]
        return name, ticker, lookback

    # 0–1: content signal overrides
    for min_novelty, credibility in [(0.7, "tier_1"), (0.8, "tier_2")]:
        for sig in content_signals:
            if (
                sig.credibility == credibility
                and sig.novelty_score > min_novelty
                and sig.suggested_chart in CHART_OPTIONS
            ):
                return _resolve(sig.suggested_chart)

    # 2: position-tagged asset with significant overnight move
    candidates = [
        ("USD/JPY", "JPY=X",  90),
        ("Gold",    "GC=F",   90),
        ("US 10Y",  "^TNX",   180),
        ("SPY",     "SPY",    90),
    ]
    for name, sym, lookback in candidates:
        if any(name.split("/")[0] in p.get("name", "") for p in positions):
            if _overnight_std_devs(name) >= 1.5:
                return name, sym, lookback

    # 3: yield curve move
    if abs(market_data.spread_change_bp) > 5:
        return _resolve("2s10s Spread")

    # 4: VIX spike
    vix_now = market_data.raw.get("VIX", 0)
    vix_prev = market_data.raw.get("VIX_prev", vix_now)
    if vix_prev and vix_now / vix_prev - 1 > 0.15:
        return _resolve("VIX")

    # 5: DXY large move
    dxy_row = next((r for r in market_data.fx if r.name == "DXY"), None)
    if dxy_row and abs(dxy_row.pct_change or 0) > 0.8:
        return _resolve("DXY")

    # 6: rotating default — different series each day of the week
    name = ROTATING_DEFAULTS[datetime.today().weekday() % len(ROTATING_DEFAULTS)]
    return _resolve(name)


def generate_chart(asset_name: str, ticker: Optional[str], lookback_days: int = 90) -> bytes:
    """Generate a Bloomberg-aesthetic PNG chart and return bytes."""
    end = datetime.today()
    start = end - timedelta(days=max(lookback_days, 365) + 15)

    series, ylabel, title = _fetch_series(asset_name, ticker, start, end)
    series = series.dropna().iloc[-lookback_days:]

    # 1yr average line — fetch extra history for the avg calculation
    full, _, _ = _fetch_series(asset_name, ticker, end - timedelta(days=380), end)
    full = full.dropna()
    yr_avg = float(full.iloc[-365:].mean()) if len(full) >= 30 else None

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    color = "#00d4aa"
    ax.plot(series.index, series.values, color=color, linewidth=1.5)
    ax.fill_between(series.index, series.values, series.values.min(), alpha=0.15, color=color)

    if yr_avg is not None:
        ax.axhline(yr_avg, color="#58a6ff", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.text(
            series.index[-1], yr_avg,
            f"  1yr avg {yr_avg:.2f}",
            color="#58a6ff", fontsize=7, va="bottom", alpha=0.7,
        )

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

    ax.text(
        0.99, 0.02, datetime.today().strftime("%Y-%m-%d"),
        transform=ax.transAxes,
        color="#30363d", fontsize=7, ha="right", va="bottom",
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fetch_series(
    asset_name: str,
    ticker: Optional[str],
    start: datetime,
    end: datetime,
) -> tuple[pd.Series, str, str]:
    if asset_name == "2s10s Spread":
        return _fetch_fred_spread(start, end), "Spread (bp)", "US 2s10s Treasury Spread"
    if asset_name == "Real Yield US 10Y":
        return _fetch_fred_single("DFII10", start, end), "Yield (%)", "US 10Y Real Yield (TIPS)"
    if asset_name == "US Financial Cond":
        return _fetch_fred_single("NFCI", start, end), "Index", "Chicago Fed National Financial Conditions Index"
    if asset_name == "Fed Funds Futures":
        return _fetch_fred_single("FEDTARMD", start, end), "Rate (%)", "Fed Funds Target Rate Median"
    if asset_name == "Oil/Gold Ratio":
        brent = yf.Ticker("BZ=F").history(start=start, end=end)["Close"].dropna()
        gold  = yf.Ticker("GC=F").history(start=start, end=end)["Close"].dropna()
        ratio = (brent / gold).dropna()
        ratio.index = pd.to_datetime(ratio.index).tz_localize(None)
        return ratio, "Ratio", "Oil/Gold Ratio (Brent ÷ Gold)"
    if asset_name == "Copper/Gold Ratio":
        copper = yf.Ticker("HG=F").history(start=start, end=end)["Close"].dropna()
        gold   = yf.Ticker("GC=F").history(start=start, end=end)["Close"].dropna()
        ratio  = (copper / gold).dropna()
        ratio.index = pd.to_datetime(ratio.index).tz_localize(None)
        return ratio, "Ratio", "Copper/Gold Ratio"
    hist = yf.Ticker(ticker).history(start=start, end=end)["Close"].dropna()
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    return hist, "Price", asset_name


def _fetch_fred_spread(start: datetime, end: datetime) -> pd.Series:
    from fredapi import Fred
    fred = Fred(api_key=cfg.FRED_API_KEY)
    y2  = fred.get_series("DGS2",  observation_start=start, observation_end=end).dropna()
    y10 = fred.get_series("DGS10", observation_start=start, observation_end=end).dropna()
    spread = (y10 - y2) * 100
    spread.index = pd.to_datetime(spread.index)
    return spread.dropna()


def _fetch_fred_single(series_id: str, start: datetime, end: datetime) -> pd.Series:
    from fredapi import Fred
    fred = Fred(api_key=cfg.FRED_API_KEY)
    s = fred.get_series(series_id, observation_start=start, observation_end=end).dropna()
    s.index = pd.to_datetime(s.index)
    return s
