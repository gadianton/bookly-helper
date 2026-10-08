"""Handoff wait message from Bookly's hours: Mon-Fri 9:00 to 18:00 America/New_York, holidays ignored."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN_HOUR, CLOSE_HOUR = 9, 18


def wait_message(now: datetime) -> str:
    now = now.astimezone(ET)
    weekday = now.weekday() < 5
    if weekday and OPEN_HOUR <= now.hour < CLOSE_HOUR:
        return "A member of our team will pick this up shortly."
    if weekday and now.hour < OPEN_HOUR:
        when = "today"
    else:
        day = now.date() + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        when = "tomorrow" if day == now.date() + timedelta(days=1) else day.strftime("%A")
    return f"Our team is back {when} at 9am ET, and a member of the team will reply then."
