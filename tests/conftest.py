from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from bookly.store import Store

TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo("America/New_York"))


@pytest.fixture
def store() -> Store:
    return Store(TODAY)
