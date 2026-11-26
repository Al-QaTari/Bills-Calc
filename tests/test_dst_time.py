"""اختبارات التوقيت: توقيت القاهرة بيتبع DST (UTC+2 شتاءً / UTC+3 صيفًا) تلقائيًا."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytz

import timeutil
from ui.home_page import get_next_auction_date

CAIRO = pytz.timezone("Africa/Cairo")


def _fixed(utc_dt):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return pytz.utc.localize(utc_dt).astimezone(tz) if tz else utc_dt

    return _DT


def test_cairo_now_winter_is_utc_plus_2():
    with patch.object(timeutil, "datetime", _fixed(datetime(2026, 12, 10, 12, 0))):
        assert timeutil.cairo_now() == datetime(2026, 12, 10, 14, 0)


def test_cairo_now_summer_is_utc_plus_3():
    with patch.object(timeutil, "datetime", _fixed(datetime(2026, 7, 10, 12, 0))):
        assert timeutil.cairo_now() == datetime(2026, 7, 10, 15, 0)


def test_offsets_differ_between_seasons():
    assert CAIRO.localize(datetime(2026, 12, 10, 12)).utcoffset() == timedelta(hours=2)
    assert CAIRO.localize(datetime(2026, 7, 10, 12)).utcoffset() == timedelta(hours=3)


def test_next_auction_keeps_wall_clock_across_dst_change():
    # الجمعة 24 أبريل 2026 الساعة 10 صباحاً شتاءً؛ العطاء القادم الأحد 26 أبريل
    # بعدها بتتغير الساعة (آخر جمعة في أبريل = 24 أبريل 2026 منتصف الليل أو قريب منه)
    now = CAIRO.localize(datetime(2026, 4, 22, 10, 0))  # الأربعاء، قبل التغيير
    nxt, name = get_next_auction_date(now)
    assert name == "الخميس"
    assert (nxt.hour, nxt.minute) == (10, 0)
    assert nxt.tzinfo is not None
