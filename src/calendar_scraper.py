"""
Module 3 — Economic Calendar.
Primary: ForexFactory HTML scrape.
Fallback: TradingEconomics API (triggered automatically on any error).
"""
from dataclasses import dataclass
from datetime import date
import random
import time
import requests
from bs4 import BeautifulSoup

FOREX_FACTORY_URL = "https://www.forexfactory.com/calendar"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Only these impact levels are included in the brief
HIGH_IMPACT_CLASSES = {"icon--ff-impact-red", "icon--ff-impact-orange"}


@dataclass
class CalendarEvent:
    time: str
    currency: str
    event: str
    forecast: str
    previous: str
    actual: str
    impact: str  # "high" or "medium"


@dataclass
class CalendarData:
    events: list
    source: str  # "forexfactory" | "tradingeconomics" | "unavailable"

    def format_telegram(self) -> str:
        today = date.today().strftime("%Y-%m-%d")
        lines = [
            f"<b>TODAY'S CALENDAR — {today}</b>\n",
            "<pre>",
            f"{'Time':<8}{'CCY':<6}{'Event':<30}{'Fcst':>8}{'Prev':>8}",
            "─" * 60,
        ]
        if not self.events:
            lines.append("No high-impact events scheduled.")
        else:
            for e in self.events:
                event_name = e.event[:28] if len(e.event) > 28 else e.event
                flag = "●" if e.impact == "high" else "○"
                lines.append(
                    f"{e.time:<8}{e.currency:<6}{flag + ' ' + event_name:<30}{e.forecast:>8}{e.previous:>8}"
                )
        if self.source != "forexfactory":
            lines.append(f"\n[Source: {self.source}]")
        lines.append("</pre>")
        return "\n".join(lines)


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def _scrape_forexfactory() -> list[CalendarEvent]:
    today = date.today()
    params = {"day": today.strftime("%b%d.%Y").lower()}
    time.sleep(random.uniform(1.0, 2.5))  # jitter
    resp = requests.get(FOREX_FACTORY_URL, params=params, headers=_random_headers(), timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", class_="calendar__table")
    if not table:
        raise ValueError("ForexFactory table not found — page structure may have changed")

    events = []
    current_time = ""

    for row in table.find_all("tr", class_="calendar__row"):
        # Time cell — may be empty if same as previous row
        time_cell = row.find("td", class_="calendar__time")
        if time_cell and time_cell.get_text(strip=True):
            current_time = time_cell.get_text(strip=True)

        # Impact
        impact_cell = row.find("td", class_="calendar__impact")
        if not impact_cell:
            continue
        impact_icon = impact_cell.find("span")
        if not impact_icon:
            continue
        icon_classes = set(impact_icon.get("class", []))
        if icon_classes & HIGH_IMPACT_CLASSES:
            impact = "high" if "icon--ff-impact-red" in icon_classes else "medium"
        else:
            continue

        currency_cell = row.find("td", class_="calendar__currency")
        event_cell = row.find("td", class_="calendar__event")
        forecast_cell = row.find("td", class_="calendar__forecast")
        previous_cell = row.find("td", class_="calendar__previous")
        actual_cell = row.find("td", class_="calendar__actual")

        events.append(CalendarEvent(
            time=current_time,
            currency=currency_cell.get_text(strip=True) if currency_cell else "",
            event=event_cell.get_text(strip=True) if event_cell else "",
            forecast=forecast_cell.get_text(strip=True) if forecast_cell else "",
            previous=previous_cell.get_text(strip=True) if previous_cell else "",
            actual=actual_cell.get_text(strip=True) if actual_cell else "",
            impact=impact,
        ))

    return events


def _fetch_trading_economics_fallback() -> list[CalendarEvent]:
    """Free TradingEconomics calendar — no API key required for basic access."""
    resp = requests.get(
        "https://tradingeconomics.com/calendar",
        headers=_random_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    events = []
    for row in soup.select("tr[data-importance='3']"):  # 3 = high impact
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


def fetch_calendar() -> CalendarData:
    try:
        events = _scrape_forexfactory()
        return CalendarData(events=events, source="forexfactory")
    except Exception:
        pass

    try:
        events = _fetch_trading_economics_fallback()
        return CalendarData(events=events, source="tradingeconomics")
    except Exception:
        pass

    return CalendarData(events=[], source="unavailable")
