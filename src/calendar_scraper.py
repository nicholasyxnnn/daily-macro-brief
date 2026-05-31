"""
Module 3 — Economic Calendar.
Primary:  Finnhub API (free tier, JSON, UTC → HKT)
Fallback: ForexFactory HTML scrape (ET → HKT)
Last:     TradingEconomics HTML scrape

All times converted to HKT. Events grouped by Asia / Europe / US session.
"""
from dataclasses import dataclass
from datetime import datetime, date, timedelta
import random
import time
import requests
from bs4 import BeautifulSoup

import config as cfg

# ── Session mapping ────────────────────────────────────────────────────────
# Handles both 3-letter currency codes (ForexFactory) and ISO-2 country codes (Finnhub)

_CURRENCY_SESSION: dict[str, str] = {
    "JPY": "ASIA", "CNY": "ASIA", "CNH": "ASIA", "AUD": "ASIA",
    "NZD": "ASIA", "KRW": "ASIA", "SGD": "ASIA", "INR": "ASIA", "IDR": "ASIA",
    "EUR": "EUROPE", "GBP": "EUROPE", "CHF": "EUROPE",
    "SEK": "EUROPE", "NOK": "EUROPE", "DKK": "EUROPE",
    "USD": "US", "CAD": "US", "BRL": "US", "MXN": "US",
}

_COUNTRY_SESSION: dict[str, str] = {
    "JP": "ASIA", "CN": "ASIA", "AU": "ASIA", "NZ": "ASIA",
    "KR": "ASIA", "SG": "ASIA", "IN": "ASIA", "ID": "ASIA",
    "EU": "EUROPE", "GB": "EUROPE", "DE": "EUROPE", "FR": "EUROPE",
    "IT": "EUROPE", "ES": "EUROPE", "CH": "EUROPE", "SE": "EUROPE", "NO": "EUROPE",
    "US": "US", "CA": "US", "BR": "US", "MX": "US",
}

_SESSION_ORDER = ["ASIA", "EUROPE", "US", "OTHER"]


def _get_session(code: str) -> str:
    return _CURRENCY_SESSION.get(code) or _COUNTRY_SESSION.get(code, "OTHER")


# ── Timezone conversion ────────────────────────────────────────────────────

def _is_us_edt(d: date) -> bool:
    """True if date falls within US EDT (2nd Sunday March → 1st Sunday November)."""
    mar1 = date(d.year, 3, 1)
    edt_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7) + timedelta(weeks=1)
    nov1 = date(d.year, 11, 1)
    edt_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return edt_start <= d < edt_end


def _et_to_hkt(time_str: str) -> str:
    """Convert ForexFactory ET string ('8:30am') to HKT 24h ('20:30')."""
    if not time_str or time_str.lower() in ("tentative", "all day", ""):
        return time_str
    try:
        t = datetime.strptime(time_str.strip().lower(), "%I:%M%p")
        hkt = t + timedelta(hours=12 if _is_us_edt(date.today()) else 13)
        return hkt.strftime("%H:%M")
    except ValueError:
        return time_str


def _utc_to_hkt(time_str: str) -> str:
    """Convert Finnhub UTC datetime string to HKT 24h ('20:30')."""
    if not time_str:
        return ""
    try:
        clean = time_str.replace("T", " ").split("+")[0].split("Z")[0].strip()
        if len(clean) <= 10:   # date-only, no time component
            return "TBD"
        t = datetime.fromisoformat(clean)
        return (t + timedelta(hours=8)).strftime("%H:%M")
    except Exception:
        return time_str


# ── Data model ────────────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    time: str       # HKT 24h string
    currency: str   # 3-letter currency or ISO-2 country code
    event: str
    forecast: str
    previous: str
    actual: str
    impact: str     # "high" or "medium"


@dataclass
class CalendarData:
    events: list
    source: str     # "finnhub" | "forexfactory" | "tradingeconomics" | "unavailable"

    def format_telegram(self) -> str:
        today = date.today().strftime("%Y-%m-%d")
        lines = [
            f"<b>TODAY'S CALENDAR — {today} (HKT)</b>\n",
            "<pre>",
        ]

        if not self.events:
            lines.append("No high-impact events scheduled.")
        else:
            sessions: dict[str, list] = {s: [] for s in _SESSION_ORDER}
            for e in self.events:
                sessions[_get_session(e.currency)].append(e)

            col = f"{'Time':<8}{'CCY':<6}{'Event':<28}{'Fcst':>8}{'Prev':>8}"
            sep = "─" * 58

            for session_name in _SESSION_ORDER:
                bucket = sorted(sessions[session_name], key=lambda x: x.time)
                if not bucket:
                    continue
                lines.append(f"▸ {session_name} SESSION")
                lines.append(col)
                lines.append(sep)
                for e in bucket:
                    flag = "●" if e.impact == "high" else "○"
                    name = (flag + " " + e.event)[:27]
                    lines.append(
                        f"{e.time:<8}{e.currency:<6}{name:<28}{e.forecast:>8}{e.previous:>8}"
                    )
                lines.append("")

        if self.source not in ("finnhub", "forexfactory"):
            lines.append(f"[Source: {self.source}]")
        lines.append("</pre>")
        return "\n".join(lines)


# ── HTTP helpers ──────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

HIGH_IMPACT_CLASSES = {"icon--ff-impact-red", "icon--ff-impact-orange"}


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


# ── Sources ───────────────────────────────────────────────────────────────

def _fetch_finnhub() -> list[CalendarEvent]:
    """Primary: Finnhub economic calendar JSON API. Times in UTC → converted to HKT."""
    if not cfg.FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY not set")
    today = date.today().isoformat()
    resp = requests.get(
        "https://finnhub.io/api/v1/calendar/economic",
        params={"from": today, "to": today, "token": cfg.FINNHUB_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    calendar = data.get("economicCalendar")
    if calendar is None:
        raise ValueError("Finnhub: missing economicCalendar in response")

    events: list[CalendarEvent] = []
    for item in calendar:
        impact = (item.get("impact") or "").lower()
        if impact not in ("high", "medium"):
            continue
        estimate = item.get("estimate")
        prev = item.get("prev")
        actual = item.get("actual")
        events.append(CalendarEvent(
            time=_utc_to_hkt(item.get("time", "")),
            currency=item.get("country", ""),
            event=item.get("event", ""),
            forecast=str(estimate) if estimate is not None else "",
            previous=str(prev) if prev is not None else "",
            actual=str(actual) if actual is not None else "",
            impact=impact,
        ))
    return events


def _scrape_forexfactory() -> list[CalendarEvent]:
    """Fallback: ForexFactory HTML scrape. Times in ET → converted to HKT."""
    today = date.today()
    params = {"day": today.strftime("%b%d.%Y").lower()}
    time.sleep(random.uniform(1.0, 2.5))
    resp = requests.get(
        "https://www.forexfactory.com/calendar",
        params=params, headers=_random_headers(), timeout=15,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", class_="calendar__table")
    if not table:
        raise ValueError("ForexFactory calendar table not found")

    events: list[CalendarEvent] = []
    current_time = ""
    for row in table.find_all("tr", class_="calendar__row"):
        time_cell = row.find("td", class_="calendar__time")
        if time_cell and time_cell.get_text(strip=True):
            current_time = time_cell.get_text(strip=True)

        impact_cell = row.find("td", class_="calendar__impact")
        if not impact_cell:
            continue
        impact_icon = impact_cell.find("span")
        if not impact_icon:
            continue
        icon_classes = set(impact_icon.get("class", []))
        if not (icon_classes & HIGH_IMPACT_CLASSES):
            continue
        impact = "high" if "icon--ff-impact-red" in icon_classes else "medium"

        def _cell(cls: str) -> str:
            c = row.find("td", class_=cls)
            return c.get_text(strip=True) if c else ""

        events.append(CalendarEvent(
            time=_et_to_hkt(current_time),
            currency=_cell("calendar__currency"),
            event=_cell("calendar__event"),
            forecast=_cell("calendar__forecast"),
            previous=_cell("calendar__previous"),
            actual=_cell("calendar__actual"),
            impact=impact,
        ))
    return events


def _fetch_trading_economics_fallback() -> list[CalendarEvent]:
    """Last resort: TradingEconomics HTML scrape."""
    resp = requests.get(
        "https://tradingeconomics.com/calendar",
        headers=_random_headers(), timeout=15,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    events: list[CalendarEvent] = []
    for row in soup.select("tr[data-importance='3']"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        events.append(CalendarEvent(
            time=cells[0].get_text(strip=True),
            currency=cells[1].get_text(strip=True),
            event=cells[3].get_text(strip=True),
            forecast=cells[4].get_text(strip=True) if len(cells) > 4 else "",
            previous=cells[5].get_text(strip=True) if len(cells) > 5 else "",
            actual=cells[6].get_text(strip=True) if len(cells) > 6 else "",
            impact="high",
        ))
    return events


# ── Entry point ───────────────────────────────────────────────────────────

def fetch_calendar() -> CalendarData:
    # 1. Finnhub — JSON API, most reliable
    try:
        return CalendarData(events=_fetch_finnhub(), source="finnhub")
    except Exception:
        pass

    # 2. ForexFactory — free HTML scrape
    try:
        return CalendarData(events=_scrape_forexfactory(), source="forexfactory")
    except Exception:
        pass

    # 3. TradingEconomics — last resort
    try:
        return CalendarData(events=_fetch_trading_economics_fallback(), source="tradingeconomics")
    except Exception:
        pass

    return CalendarData(events=[], source="unavailable")
