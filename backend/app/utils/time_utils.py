from datetime import date, datetime
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now_shanghai() -> datetime:
    """Return naive Asia/Shanghai time for storage in existing DATETIME columns."""
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def today_shanghai() -> date:
    return now_shanghai().date()
