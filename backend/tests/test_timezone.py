from datetime import UTC, datetime

from app.core.timezone import BEIJING_TZ, as_beijing, beijing_now, isoformat_beijing


def test_beijing_now_uses_east_eight_timezone() -> None:
    assert beijing_now().utcoffset().total_seconds() == 8 * 60 * 60


def test_isoformat_beijing_converts_aware_datetime() -> None:
    value = datetime(2026, 5, 13, 1, 30, tzinfo=UTC)

    assert isoformat_beijing(value) == "2026-05-13T09:30:00+08:00"


def test_as_beijing_treats_naive_datetime_as_beijing_record() -> None:
    value = datetime(2026, 5, 13, 9, 30)

    assert as_beijing(value) == value.replace(tzinfo=BEIJING_TZ)
