"""
اختبارات الإصلاحين:
1) عداد الفشل المتتالي المحفوظ بين التشغيلات (FailureTracker في update_data.py).
2) فحص معقولية البيانات المسحوبة قبل الحفظ (validate_scraped_data في cbe_scraper.py).
"""

import logging

import pandas as pd
import pytest

from cbe_scraper import validate_scraped_data
from update_data import FailureTracker


# =============================================================================
# FailureTracker
# =============================================================================
def _tracker(tmp_path) -> FailureTracker:
    # بدون محرك قاعدة: يعتمد على ملف JSON في مجلد مؤقت
    return FailureTracker(engine=None, state_file=tmp_path / "update_state.json")


def test_failure_count_persists_across_instances(tmp_path):
    """المشكلة الأصلية: العداد كان في الذاكرة فيتصفّر مع كل تشغيل جديد."""
    t1 = _tracker(tmp_path)
    assert t1.increment() == 1
    assert t1.increment() == 2

    # «تشغيل جديد» = كائن جديد تمامًا — لازم يكمل من 2 مش من الصفر
    t2 = _tracker(tmp_path)
    assert t2.get_count() == 2
    assert t2.increment() == 3


def test_failure_count_reset_clears_persisted_value(tmp_path):
    t1 = _tracker(tmp_path)
    t1.increment()
    t1.increment()
    t1.reset()

    t2 = _tracker(tmp_path)
    assert t2.get_count() == 0


def test_failure_tracker_memory_fallback(tmp_path):
    """لو الملف اتقرأش لأي سبب، الذاكرة بتغطي داخل نفس العملية."""
    t = _tracker(tmp_path)
    t.state_file = tmp_path / "missing_dir" / "update_state.json"
    assert t.increment() >= 1


# =============================================================================
# validate_scraped_data
# =============================================================================
def _valid_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tenor": [91, 182, 273, 364],
            "yield": [26.5, 26.8, 27.0, 27.2],
            "session_date": ["22/11/2026"] * 4,
        }
    )


def test_validate_accepts_plausible_data():
    out = validate_scraped_data(_valid_df())
    assert len(out) == 4
    assert out["yield"].dtype.kind == "f"


def test_validate_rejects_empty():
    with pytest.raises(ValueError, match="فارغة"):
        validate_scraped_data(pd.DataFrame())


def test_validate_rejects_missing_columns():
    df = _valid_df().drop(columns=["yield"])
    with pytest.raises(ValueError, match="ناقصة"):
        validate_scraped_data(df)


@pytest.mark.parametrize("bad_yield", [-1.0, 0.0, 2500000.0, 100.0])
def test_validate_rejects_implausible_yield(bad_yield):
    """مبالغ بملايين مكان العوائد = قراءة عمود غلط بعد تغيير شكل الصفحة."""
    df = _valid_df()
    df.loc[0, "yield"] = bad_yield
    with pytest.raises(ValueError, match="خارج النطاق المعقول"):
        validate_scraped_data(df)


def test_validate_rejects_non_numeric_yield():
    df = _valid_df()
    df.loc[0, "yield"] = "غير متاح"
    with pytest.raises(ValueError, match="غير رقمية"):
        validate_scraped_data(df)


def test_validate_rejects_implausible_tenor():
    df = _valid_df()
    df.loc[0, "tenor"] = 5000
    with pytest.raises(ValueError, match="أجل خارج النطاق"):
        validate_scraped_data(df)


def test_validate_rejects_future_session_date():
    df = _valid_df()
    df["session_date"] = "22/11/2099"
    with pytest.raises(ValueError, match="في المستقبل"):
        validate_scraped_data(df)


def test_validate_rejects_unparseable_session_date():
    df = _valid_df()
    df["session_date"] = "ليس تاريخًا"
    with pytest.raises(ValueError, match="غير مقروءة"):
        validate_scraped_data(df)


def test_validate_warns_on_big_jump_but_accepts(caplog):
    """قفزة كبيرة عن آخر جلسة = تحذير فقط، ممكن تكون حركة سوق حقيقية."""
    previous = pd.DataFrame(
        {
            "tenor": [91, 182, 273, 364],
            "yield": [26.0, 26.5, 27.0, 27.5],
            "session_date": ["19/11/2026"] * 4,
        }
    )
    new = _valid_df()
    new.loc[0, "yield"] = 36.5  # قفزة 10.5 نقطة لأجل 91

    with caplog.at_level(logging.WARNING):
        out = validate_scraped_data(new, previous_data=previous)

    assert len(out) == 4  # اتقبلت
    assert any("قفزة كبيرة" in rec.message for rec in caplog.records)


def test_validate_no_warning_on_small_move(caplog):
    previous = pd.DataFrame(
        {
            "tenor": [91, 182, 273, 364],
            "yield": [26.4, 26.7, 26.9, 27.1],
            "session_date": ["19/11/2026"] * 4,
        }
    )
    with caplog.at_level(logging.WARNING):
        validate_scraped_data(_valid_df(), previous_data=previous)
    assert not any("قفزة كبيرة" in rec.message for rec in caplog.records)
