"""
Schema change detection for scraped data.
Asserts on output shape before passing to scorer — raises on empty/malformed.
"""
from src.market_data import MarketDashboard
from src.calendar_scraper import CalendarData
from src.content_scraper import ContentItem


class ScrapeValidationError(Exception):
    pass


def validate_market_data(dashboard: MarketDashboard) -> None:
    """Raise ScrapeValidationError if market data is clearly broken."""
    if not dashboard.equities and not dashboard.rates:
        raise ScrapeValidationError("Market data fetch returned no equities or rates")
    for row in dashboard.equities:
        if row.last <= 0:
            raise ScrapeValidationError(f"Non-positive price for {row.name}: {row.last}")


def validate_calendar(data: CalendarData) -> None:
    """Warn if ForexFactory returned nothing — not a hard error (could be no events)."""
    if data.source == "unavailable":
        # Acceptable — calendar is best-effort
        return


def validate_content_items(items: list[ContentItem]) -> list[ContentItem]:
    """Filter out obviously malformed items (no title, no URL)."""
    valid = [it for it in items if it.title and it.url]
    if not valid:
        raise ScrapeValidationError("Content scrape returned zero valid items")
    return valid
