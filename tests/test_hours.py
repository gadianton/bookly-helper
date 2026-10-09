from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bookly.hours import wait_message

ET = ZoneInfo("America/New_York")


# 2026-10-03 is a Saturday.
@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 10, 3, 14, 0, tzinfo=ET), "Monday at 9am ET"),
        (datetime(2026, 10, 7, 10, 0, tzinfo=ET), "shortly"),
        (datetime(2026, 10, 9, 18, 0, tzinfo=ET), "Monday at 9am ET"),
        (datetime(2026, 10, 6, 7, 30, tzinfo=ET), "today at 9am ET"),
    ],
)
def test_wait_message_at_hour_boundaries(now, expected):
    assert expected in wait_message(now)
