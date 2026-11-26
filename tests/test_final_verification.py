# tests/test_final_verification.py
"""
اختبارات تحقق نهائية (كتبها فريق المراجعة):
1) اتساق تعريف الآجال في كل الملفات.
2) إصلاح "غير متاح": load_latest_data يرجع كل الآجال الحالية فقط، مرتبة، بدون حذف عشوائي.
3) دقة الحسابات لكل الآجال بحساب كسري دقيق مستقل (Fraction) مقابل محرك Decimal.
4) مسار تنبيهات تليجرام كامل مع إرسال وهمي (mock) - بدون أي إرسال حقيقي.
5) إعادة المحاولة async في backoff_retry.
"""

import os
import sys
import asyncio
from decimal import Decimal
from fractions import Fraction

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import constants as C
from db_manager import SQLiteDBManager
from treasury_core.calculations import calculate_primary_yield, analyze_secondary_sale
from treasury_core.models import PrimaryYieldInput, SecondarySaleInput

# ---------- 1) اتساق الآجال ----------


def test_tenors_definition_is_current():
    """الآجال الحالية هي 91/182/273/357 فقط، ولا وجود لـ 364 أو 336."""
    assert C.TENORS == [91, 182, 273, 357]
    assert 364 not in C.TENORS and 336 not in C.TENORS
    assert C.INITIAL_DATA[C.TENOR_COLUMN_NAME] == C.TENORS
    assert len(C.INITIAL_DATA[C.YIELD_COLUMN_NAME]) == len(C.TENORS)
    assert len(C.INITIAL_DATA[C.SESSION_DATE_COLUMN_NAME]) == len(C.TENORS)


def test_no_discontinued_tenors_anywhere_in_source():
    """لا يوجد أي ذكر للآجال الملغاة في ملفات التطبيق (خارج الاختبارات والحسابات المرجعية)."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    app_files = [
        "app.py",
        "constants.py",
        "utils.py",
        "db_manager.py",
        "postgres_manager.py",
        "cbe_scraper.py",
        "update_data.py",
        "secret_admin_panel.py",
        "ui/home_page.py",
        "ui/primary_yield_calculator.py",
        "ui/secondary_sale_calculator.py",
        "ui/historical_data_view.py",
        "ui/help_page.py",
        "factories.py",
        "treasury_core/calculations.py",
        "treasury_core/models.py",
    ]
    for rel in app_files:
        text = (root / rel).read_text(encoding="utf-8")
        for dead in ("364", "336"):
            assert not re.search(
                rf"(?<!\d){dead}(?!\d)", text
            ), f"{rel} still mentions tenor {dead}"


# ---------- 2) إصلاح "غير متاح" ----------


@pytest.fixture
def seeded_db(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "t.db")
    rows = []
    # جلستان حديثتان بالآجال الحالية + بقايا آجال ملغاة (336 و364) بتواريخ أحدث
    for tenor, y in [(91, 24.9), (182, 25.3), (273, 26.2), (357, 26.1)]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: "19/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-19"),
            }
        )
    for tenor, y in [(336, 27.0), (364, 26.07)]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: "12/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-12"),
            }
        )
    db.save_data(pd.DataFrame(rows))
    return db


def test_load_latest_returns_all_current_tenors_only(seeded_db):
    df, (d, t) = seeded_db.load_latest_data()
    assert sorted(df[C.TENOR_COLUMN_NAME].tolist()) == [91, 182, 273, 357]
    # مرتبة تصاعديًا بشكل ثابت
    assert df[C.TENOR_COLUMN_NAME].tolist() == sorted(df[C.TENOR_COLUMN_NAME].tolist())
    assert d == "2026-11-19"


def test_load_latest_no_random_dropping_with_many_tenors(tmp_path):
    """إعادة إنتاج عطل LIMIT: 6 آجال في القاعدة يجب ألا يحذف أي أجل حالي."""
    db = SQLiteDBManager(db_filename=tmp_path / "t2.db")
    rows = []
    for tenor in [91, 182, 273, 336, 357, 364]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: 25.0,
                C.SESSION_DATE_COLUMN_NAME: "19/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-19"),
            }
        )
    db.save_data(pd.DataFrame(rows))
    df, _ = db.load_latest_data()
    assert len(df) == 4
    assert set(df[C.TENOR_COLUMN_NAME]) == set(C.TENORS)


# ---------- 3) دقة الحسابات (كسور دقيقة) ----------

LIVE_YIELDS = {91: "24.917", 182: "25.358", 273: "26.289", 357: "26.165"}


def exact_primary(face, yield_pct, tenor, tax_pct):
    f, y, d, tx = (
        Fraction(str(face)),
        Fraction(str(yield_pct)),
        Fraction(tenor),
        Fraction(str(tax_pct)),
    )
    price = f / (1 + y / 100 * d / 365)
    gross = f - price
    tax = gross * tx / 100
    net = gross - tax
    real = (net / price) * 100
    return price, gross, tax, net, real


@pytest.mark.parametrize("tenor", [91, 182, 273, 357])
@pytest.mark.parametrize("face", ["1000000", "4000000"])
def test_primary_calc_matches_exact_fraction_math(tenor, face):
    res = calculate_primary_yield(
        PrimaryYieldInput(
            face_value=float(face),
            yield_rate=float(LIVE_YIELDS[tenor]),
            tenor=tenor,
            tax_rate=20.0,
        )
    )
    price, gross, tax, net, real = exact_primary(face, LIVE_YIELDS[tenor], tenor, 20)
    for app_val, exact in [
        (res.purchase_price, price),
        (res.gross_return, gross),
        (res.tax_amount, tax),
        (res.net_return, net),
        (res.real_profit_percentage, real),
    ]:
        diff = abs(
            Decimal(str(app_val))
            - Decimal(exact.numerator) / Decimal(exact.denominator)
        )
        assert diff < Decimal("0.0000001"), f"tenor={tenor} face={face} diff={diff}"


def test_357_reference_values():
    """القيم المرجعية لأجل 357 على مليون جنيه (محسوبة يدويًا بالكسور)."""
    res = calculate_primary_yield(
        PrimaryYieldInput(
            face_value=1_000_000.0, yield_rate=26.165, tenor=357, tax_rate=20.0
        )
    )
    assert abs(float(res.purchase_price) - 796232.10) < 0.01
    assert abs(float(res.gross_return) - 203767.90) < 0.01
    assert abs(float(res.tax_amount) - 40753.58) < 0.01
    assert abs(float(res.net_return) - 163014.32) < 0.01


def test_secondary_sale_357_exact():
    res = analyze_secondary_sale(
        SecondarySaleInput(
            face_value=1_000_000.0,
            original_yield=26.165,
            original_tenor=357,
            holding_days=100,
            secondary_yield=25.0,
            tax_rate=20.0,
        )
    )
    assert abs(float(res.original_purchase_price) - 796232.10) < 0.01
    assert abs(float(res.sale_price) - 850320.33) < 0.01
    assert abs(float(res.net_profit) - 43270.58) < 0.01
    # خسارة: الضريبة صفر
    res2 = analyze_secondary_sale(
        SecondarySaleInput(
            face_value=1_000_000.0,
            original_yield=26.165,
            original_tenor=357,
            holding_days=100,
            secondary_yield=60.0,
            tax_rate=20.0,
        )
    )
    assert float(res2.tax_amount) == 0.0
    assert float(res2.net_profit) < 0


# ---------- 4) مسار تليجرام (إرسال وهمي - لا شبكة حقيقية) ----------


class _FakeResponse:
    ok = True
    status_code = 200
    text = "OK"


def test_telegram_full_pipeline_fake_send(tmp_path, monkeypatch):
    """المسار الكامل: كشف تغيير العائد -> توليد الرسالة -> إرسال (وهمي) -> تسجيل الإرسال."""
    import update_data

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "FAKE_TOKEN_FOR_TEST")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv("ALERTS_ENABLED", "true")
    # عزل كاش التنبيهات في ملف مؤقت (الافتراضي مرتبط بملف المشروع)
    real_alert_manager = update_data.AlertManager
    monkeypatch.setattr(
        update_data,
        "AlertManager",
        lambda **kw: real_alert_manager(cache_file=tmp_path / "alerts.json", **kw),
    )

    sent = []

    class FakeSession:
        def post(self, url, json=None, timeout=None):
            sent.append((url, json))
            return _FakeResponse()

    monkeypatch.setattr(update_data, "HTTP_SESSION", FakeSession())

    class StubDB:
        def check_yield_changes(self, threshold_percent=0.5):
            return [
                {
                    "tenor": 357,
                    "latest_yield": 26.165,
                    "previous_yield": 25.70,
                    "change_percent": 1.81,
                    "direction": "زيادة",
                    "latest_date": "2026-11-19",
                    "previous_date": "2026-11-12",
                }
            ]

    update_data._check_and_send_telegram_alerts_blocking(StubDB())

    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "https://api.telegram.org/botFAKE_TOKEN_FOR_TEST/sendMessage"
    assert payload["chat_id"] == "123456"
    assert "357" in payload["text"]
    assert "26.165" in payload["text"]
    assert "📈" in payload["text"]

    # ثاني مرة: نفس التنبيه لا يُرسل مرة أخرى (منع التكرار)
    update_data._check_and_send_telegram_alerts_blocking(StubDB())
    assert len(sent) == 1


def test_telegram_not_sent_without_credentials(monkeypatch):
    """بدون توكن/معرف: لا إرسال إطلاقًا."""
    import update_data

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert update_data._send_telegram_alert_sync({"tenor": 357}) is False


def test_telegram_message_escapes_html():
    import update_data

    msg = update_data._generate_telegram_message(
        {
            "tenor": "357<script>",
            "latest_yield": 26.165,
            "previous_yield": 25.7,
            "change_percent": 1.81,
            "direction": "زيادة",
        }
    )
    assert "<script>" not in msg
    assert "357" in msg


# ---------- 5) إعادة المحاولة async ----------


def test_backoff_retry_actually_retries_async_functions():
    from backoff_retry import backoff_retry

    calls = {"n": 0}

    @backoff_retry(max_retries=3, base_delay=0.01, jitter=False)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("فشل مؤقت")
        return "نجح"

    assert asyncio.run(flaky()) == "نجح"
    assert calls["n"] == 3


def test_backoff_retry_async_gives_up_after_max():
    from backoff_retry import backoff_retry

    calls = {"n": 0}

    @backoff_retry(max_retries=2, base_delay=0.01, jitter=False)
    async def always_fails():
        calls["n"] += 1
        raise RuntimeError("فشل دائم")

    with pytest.raises(RuntimeError):
        asyncio.run(always_fails())
    assert calls["n"] == 3  # المحاولة الأولى + محاولتان


# ---------- 6) إصلاح تنبيهات تليجرام الأوتوماتيكية (المقارنة لكل أجل على حدة) ----------


def _seed_two_sessions(db):
    """عطاء خميس قديم وأحدث لـ 182/357 + عطاء أحد لـ 91/273 بينهما."""
    rows = []
    # الخميس 12/11 (قديم): 182 و357
    for tenor, y in [(182, 25.0), (357, 25.70)]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: "12/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-12"),
            }
        )
    # الأحد 15/11: 91 و273
    for tenor, y in [(91, 24.9), (273, 26.2)]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: "15/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-15"),
            }
        )
    # الخميس 19/11 (أحدث): 182 شبه ثابت، 357 ارتفع > 0.5%
    for tenor, y in [(182, 25.03), (357, 26.165)]:
        rows.append(
            {
                C.TENOR_COLUMN_NAME: tenor,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: "19/11/2026",
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-11-19"),
            }
        )
    db.save_data(pd.DataFrame(rows))


def test_alert_fires_for_thursday_tenor_change(tmp_path):
    """قبل الإصلاح: تنبيه 357 كان يضيع لأن المقارنة كانت بتاريخ الأحد المشترك."""
    db = SQLiteDBManager(db_filename=tmp_path / "alerts.db")
    _seed_two_sessions(db)
    alerts = db.check_yield_changes(threshold_percent=0.5)
    tenors = {a["tenor"] for a in alerts}
    assert 357 in tenors, f"يجب أن يظهر تنبيه 357 - وصل: {alerts}"
    a357 = next(a for a in alerts if a["tenor"] == 357)
    assert a357["direction"] == "زيادة"
    assert a357["latest_date"] == "2026-11-19"
    assert a357["previous_date"] == "2026-11-12"
    # 182 تغير 0.12% فقط: تحت الحد، بدون تنبيه
    assert 182 not in tenors
    # 91 و273 لهم جلسة واحدة لكل منهم: لا مقارنة ممكنة، لا تنبيه
    assert 91 not in tenors and 273 not in tenors


def test_no_alerts_when_yields_stable(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "stable.db")
    rows = []
    for tenor, y1, y2 in [(182, 25.0, 25.01), (357, 26.0, 26.02)]:
        for sd, y in [("12/11/2026", y1), ("19/11/2026", y2)]:
            rows.append(
                {
                    C.TENOR_COLUMN_NAME: tenor,
                    C.YIELD_COLUMN_NAME: y,
                    C.SESSION_DATE_COLUMN_NAME: sd,
                    C.DATE_COLUMN_NAME: pd.to_datetime(sd, dayfirst=True),
                }
            )
    db.save_data(pd.DataFrame(rows))
    assert db.check_yield_changes(threshold_percent=0.5) == []
