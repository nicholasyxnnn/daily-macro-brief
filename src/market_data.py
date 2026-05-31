from dataclasses import dataclass, field
from typing import Optional
from datetime import date
import yfinance as yf
import pandas as pd
from fredapi import Fred
import config as cfg

# --- Ticker maps ---

EQUITY_TICKERS = {
    "SPY":    "SPY",
    "QQQ":    "QQQ",
    "DJI":    "^DJI",
    "DAX":    "^GDAXI",
    "FTSE":   "^FTSE",
    "CAC":    "^FCHI",
    "Nikkei": "^N225",
    "HSI":    "^HSI",
    "CSI300": "000300.SS",
}

FX_TICKERS = {
    "DXY":     "DX-Y.NYB",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CNH": "CNH=X",
}

COMMODITY_TICKERS = {
    "Gold":  "GC=F",
    "WTI":   "CL=F",
    "Brent": "BZ=F",
}

CRYPTO_TICKERS = {
    "BTC": "BTC-USD",
}

VIX_TICKER = "^VIX"

FRED_SERIES = {
    "US 2Y":  "DGS2",
    "US 10Y": "DGS10",
    "US 30Y": "DGS30",
}

EU_RATE_TICKERS = {
    "Bund 10Y": "^TMBMKDE-10Y",
    "Gilt 10Y": "^TMBMKGB-10Y",
}


@dataclass
class AssetRow:
    name: str
    last: float
    change: float
    pct_change: Optional[float] = None
    bp_change: Optional[float] = None
    is_rate: bool = False


@dataclass
class MarketDashboard:
    as_of: str
    equities: list
    rates: list
    fx: list
    commodities: list
    crypto: list
    spread_2s10s: float
    spread_change_bp: float
    # raw numeric values for chart.py std-dev calculations
    raw: dict = field(default_factory=dict)

    def format_telegram(self) -> str:
        today = date.today().strftime("%Y-%m-%d")
        lines = [
            f"<b>OVERNIGHT DASHBOARD — {today}</b>\n",
            "<pre>",
            f"{'Asset':<14}{'Last':>10}{'Chg':>10}{'Chg%/bp':>10}",
            "─" * 44,
        ]

        def equity_line(r: AssetRow) -> str:
            sign = "+" if r.change >= 0 else ""
            sign_p = "+" if r.pct_change >= 0 else ""
            return f"{r.name:<14}{r.last:>10,.1f}{sign + f'{r.change:,.1f}':>10}{sign_p + f'{r.pct_change:.1f}%':>10}"

        def rate_line(r: AssetRow) -> str:
            sign = "+" if r.bp_change >= 0 else ""
            return f"{r.name:<14}{r.last:>9.2f}%{sign + f'{r.bp_change:.0f}bp':>10}"

        lines.append("EQUITIES")
        for r in self.equities:
            lines.append(equity_line(r))

        lines.append("FX")
        for r in self.fx:
            lines.append(equity_line(r))

        lines.append("RATES")
        for r in self.rates:
            lines.append(rate_line(r))
        sign = "+" if self.spread_change_bp >= 0 else ""
        spread_val = f"{self.spread_2s10s:+.0f}bp"
        spread_chg = f"{sign}{self.spread_change_bp:.0f}bp"
        lines.append(f"{'2s10s':<14}{spread_val:>10}{spread_chg:>10}")

        lines.append("COMMODITIES")
        for r in self.commodities:
            lines.append(equity_line(r))

        lines.append("CRYPTO")
        for r in self.crypto:
            lines.append(equity_line(r))

        lines.append("</pre>")
        return "\n".join(lines)


def _fetch_yf_rows(ticker_map: dict) -> list[AssetRow]:
    rows = []
    symbols = list(ticker_map.values())
    data = yf.download(symbols, period="5d", auto_adjust=True, progress=False)

    close = data["Close"] if len(symbols) > 1 else data[["Close"]].rename(columns={"Close": symbols[0]})

    for name, sym in ticker_map.items():
        try:
            series = close[sym].dropna()
            if len(series) < 2:
                continue
            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            chg = last - prev
            pct = chg / prev * 100
            rows.append(AssetRow(name=name, last=last, change=chg, pct_change=pct))
        except Exception:
            continue
    return rows


def _fetch_fred_rates() -> tuple[list[AssetRow], dict]:
    fred = Fred(api_key=cfg.FRED_API_KEY)
    rate_rows = []
    raw = {}
    for name, series_id in FRED_SERIES.items():
        try:
            s = fred.get_series(series_id).dropna()
            if len(s) < 2:
                continue
            last = float(s.iloc[-1])
            prev = float(s.iloc[-2])
            bp_chg = (last - prev) * 100
            rate_rows.append(AssetRow(name=name, last=last, change=last - prev, bp_change=bp_chg, is_rate=True))
            raw[name] = last
        except Exception:
            continue
    return rate_rows, raw


def _fetch_eu_rates() -> list[AssetRow]:
    rows = []
    for name, sym in EU_RATE_TICKERS.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            series = hist["Close"].dropna()
            if len(series) < 2:
                continue
            last = float(series.iloc[-1])
            prev = float(series.iloc[-2])
            bp_chg = (last - prev) * 100
            rows.append(AssetRow(name=name, last=last, change=last - prev, bp_change=bp_chg, is_rate=True))
        except Exception:
            continue
    return rows


def fetch_market_data() -> MarketDashboard:
    equities = _fetch_yf_rows(EQUITY_TICKERS)
    fx = _fetch_yf_rows(FX_TICKERS)
    commodities = _fetch_yf_rows(COMMODITY_TICKERS)
    crypto = _fetch_yf_rows(CRYPTO_TICKERS)

    rate_rows, raw_rates = _fetch_fred_rates()
    eu_rates = _fetch_eu_rates()
    all_rates = rate_rows + eu_rates

    # 2s10s spread
    y2 = raw_rates.get("US 2Y", 0.0)
    y10 = raw_rates.get("US 10Y", 0.0)
    spread_now = (y10 - y2) * 100  # in bp

    # previous spread — recompute from rate rows if available
    spread_prev = 0.0
    row_2y = next((r for r in rate_rows if r.name == "US 2Y"), None)
    row_10y = next((r for r in rate_rows if r.name == "US 10Y"), None)
    if row_2y and row_10y:
        prev_2y = y2 - row_2y.change
        prev_10y = y10 - row_10y.change
        spread_prev = (prev_10y - prev_2y) * 100
    spread_change = spread_now - spread_prev

    # raw dict for chart.py (prices indexed by name)
    raw = {r.name: r.last for r in equities + fx + commodities + crypto}
    raw.update(raw_rates)
    raw["2s10s"] = spread_now

    # vix for chart selection
    try:
        vix_hist = yf.Ticker(VIX_TICKER).history(period="5d")["Close"].dropna()
        if len(vix_hist) >= 2:
            raw["VIX"] = float(vix_hist.iloc[-1])
            raw["VIX_prev"] = float(vix_hist.iloc[-2])
    except Exception:
        pass

    return MarketDashboard(
        as_of=date.today().isoformat(),
        equities=equities,
        rates=all_rates,
        fx=fx,
        commodities=commodities,
        crypto=crypto,
        spread_2s10s=spread_now,
        spread_change_bp=spread_change,
        raw=raw,
    )
