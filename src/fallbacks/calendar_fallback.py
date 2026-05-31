from src.calendar_scraper import CalendarData


def get_calendar_fallback() -> CalendarData:
    return CalendarData(events=[], source="unavailable")
