# tests/test_extra_coverage.py
"""تغطية إضافية: الأدوات المساعدة، تواريخ العطاءات، الكاش، والتنبيهات."""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import format_currency, prepare_arabic_text
from ui.home_page import get_next_auction_date, format_countdown

# ---------- utils ----------


def test_format_currency_basic():
    assert format_currency(1234567.891) == "1,234,567.89 جنيه"
    assert format_currency(-50.5) == "-50.50 جنيه"
    assert format_currency(None) == "- جنيه"
    assert format_currency(0) == "0.00 جنيه"


def test_prepare_arabic_text():
    assert prepare_arabic_text("أذون") == "أذون"
    assert prepare_arabic_text(123) == "123"


# ---------- مواعيد العطاءات ----------


@pytest.mark.parametrize(
    "day,expected_weekday",
    [
        (datetime(2026, 11, 25), 3),  # الأربعاء -> الخميس
        (datetime(2026, 11, 26), 3),  # الخميس نفسه
        (datetime(2026, 11, 27), 6),  # الجمعة -> الأحد
        (datetime(2026, 11, 28), 6),  # السبت -> الأحد
        (datetime(2026, 11, 22), 6),  # الأحد نفسه
        (datetime(2026, 11, 23), 3),  # الاثنين -> الخميس
    ],
)
def test_next_auction_date(day, expected_weekday):
    nxt, name = get_next_auction_date(day)
    assert nxt.weekday() == expected_weekday
    assert name == ("الخميس" if expected_weekday == 3 else "الأحد")
    assert nxt.date() >= day.date()
    assert (nxt.date() - day.date()).days <= 4


def test_format_countdown():
    assert format_countdown(timedelta(days=1, hours=2)) == "1 يوم و 2 ساعة"
    assert format_countdown(timedelta(hours=5)) == "5 ساعة"
    assert format_countdown(timedelta(minutes=30)) == "30 دقيقة"
    assert format_countdown(timedelta(seconds=10)) == "قريباً جداً"


# ---------- الكاش بدون redis ----------


def test_enhanced_cache_without_redis_is_safe():
    from enhanced_cache import EnhancedCache

    cache = EnhancedCache(redis_client=None, key_prefix="t")
    assert cache.get("df_latest") is None
    assert cache.set("df_latest", pd.DataFrame({"a": [1]})) is False
    assert cache.invalidate("df_latest") is False
    assert cache.exists("df_latest") is False
    assert cache.invalidate_pattern("*") == 0


# ---------- AlertManager في update_data ----------


def test_alert_manager_dedupe_and_expiry(tmp_path, monkeypatch):
    import update_data

    mgr = update_data.AlertManager(cache_file=tmp_path / "a.json")
    alert = {
        "tenor": 357,
        "latest_yield": 26.165,
        "previous_yield": 25.7,
        "change_percent": 1.81,
        "direction": "زيادة",
        "latest_date": "2026-11-19",
        "previous_date": "2026-10-15",
    }
    assert mgr.is_duplicate(alert) is False
    mgr.mark_sent(alert)
    assert mgr.is_duplicate(alert) is True

    # إدخال قديم (أكثر من 24 ساعة) لا يحجب التنبيه
    h = mgr._generate_hash(alert)
    mgr.cache["alerts"][h]["timestamp"] = "2020-01-01T00:00:00"
    assert mgr.is_duplicate(alert) is False


def test_telegram_check_disabled_by_env(tmp_path, monkeypatch):
    """ALERTS_ENABLED=false => لا فحص ولا إرسال إطلاقًا."""
    import update_data

    monkeypatch.setenv("ALERTS_ENABLED", "false")
    called = []

    class StubDB:
        def check_yield_changes(self, threshold_percent=0.5):
            called.append(1)
            return [{"tenor": 357}]

    update_data._check_and_send_telegram_alerts_blocking(StubDB())
    assert called == []


# ---------- طبقة PostgreSQL تحمل نفس الإصلاح ----------


def test_postgres_load_latest_filters_current_tenors():
    """التحقق النصي: استعلام PostgreSQL فيه فلتر الآجال الحالية وترتيب ثابت."""
    import inspect
    import postgres_manager

    src = inspect.getsource(postgres_manager.PostgresDBManager.load_latest_data)
    assert "IN ({tenors_sql})" in src
    assert "ORDER BY" in src


def test_sqlite_load_latest_has_no_limit():
    import inspect
    import db_manager

    import re

    src = inspect.getsource(db_manager.SQLiteDBManager.load_latest_data)
    # لا يوجد استعلام بـ LIMIT عددي (التعليقات العربية مسموح بها)
    assert not re.search(r"\bLIMIT\s*[\d{]", src)
    assert "IN ({tenors_sql})" in src
    assert "ORDER BY" in src


# ---------- سكريبت التحديث لا يثبت playwright مع كل تشغيل ----------


def test_update_data_does_not_reinstall_playwright():
    import inspect
    import update_data

    assert not hasattr(update_data, "_ensure_playwright_is_installed_for_cron")
    src = inspect.getsource(update_data.main)
    assert "playwright install" not in src
