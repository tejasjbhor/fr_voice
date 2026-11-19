"""Schedule due-window logic — no live calls."""

from datetime import datetime
from zoneinfo import ZoneInfo

from telephony.daily_calls import user_is_due

IST = ZoneInfo("Asia/Kolkata")


def _user(**over):
    row = {
        "id": 1,
        "active": 1,
        "account_role": "user",
        "schedule_enabled": 1,
        "phone": "+919800000002",
        "timezone": "Asia/Kolkata",
        "days_of_week": "1,2,3,4,5,6,7",
        "call_time": "09:00",
        "last_scheduled_on": None,
        "skip_on": None,
    }
    row.update(over)
    return row


def test_due_at_call_time():
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)
    assert user_is_due(_user(), now.astimezone(ZoneInfo("UTC"))) is True


def test_not_due_before_call_time():
    now = datetime(2026, 8, 18, 8, 59, tzinfo=IST)
    assert user_is_due(_user(), now.astimezone(ZoneInfo("UTC"))) is False


def test_subscriber_never_due():
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)
    assert user_is_due(_user(account_role="subscriber"), now.astimezone(ZoneInfo("UTC"))) is False


def test_paused_not_due():
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)
    assert user_is_due(_user(schedule_enabled=0), now.astimezone(ZoneInfo("UTC"))) is False


def test_skip_today():
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)
    assert user_is_due(_user(skip_on="2026-08-18"), now.astimezone(ZoneInfo("UTC"))) is False


def test_already_called_today():
    now = datetime(2026, 8, 18, 9, 5, tzinfo=IST)
    assert user_is_due(_user(last_scheduled_on="2026-08-18"), now.astimezone(ZoneInfo("UTC"))) is False


def test_weekday_filter():
    # 2026-08-18 is a Tuesday (ISO 2)
    now = datetime(2026, 8, 18, 9, 0, tzinfo=IST)
    assert user_is_due(_user(days_of_week="1,3,4,5"), now.astimezone(ZoneInfo("UTC"))) is False
    assert user_is_due(_user(days_of_week="2"), now.astimezone(ZoneInfo("UTC"))) is True
