"""اختبارات توحيد الأجل واكتشاف الآجال الحالية تلقائيًا (364/357/336 = أذن سنة)."""

import pandas as pd
import pytest

import constants as C
from db_manager import SQLiteDBManager
from tenors import (
    active_tenors,
    calc_days,
    auction_day_groups,
    group_label,
    latest_active_rows,
    normalize_tenor,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (364, 364),
        (357, 364),
        (336, 364),
        (91, 91),
        (182, 182),
        (273, 273),
        (270, 273),
        (180, 182),
        (728, 728),
        (30, 30),
        ("357", 364),
    ],
)
def test_normalize(raw, expected):
    assert normalize_tenor(raw) == expected


def _row(t, y, sess, scrape):
    return {
        C.TENOR_COLUMN_NAME: t,
        C.YIELD_COLUMN_NAME: y,
        C.SESSION_DATE_COLUMN_NAME: sess,
        C.DATE_COLUMN_NAME: pd.to_datetime(scrape),
    }


def test_flip_364_357_364_gives_one_continuous_series(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "f.db")
    rows = [
        _row(364, 25.0, "05/11/2026", "2026-11-05"),
        _row(364, 25.1, "12/11/2026", "2026-11-12"),
        _row(357, 25.2, "19/11/2026", "2026-11-19"),
        _row(364, 25.4, "26/11/2026", "2026-11-26"),
    ]
    for r in rows:
        db.save_data(pd.DataFrame([r]))
    hist = db.load_all_historical_data()
    assert set(hist[C.TENOR_COLUMN_NAME]) == {364}
    assert len(hist) == 4
    latest, _ = db.load_latest_data()
    assert latest[C.TENOR_COLUMN_NAME].tolist() == [364]
    assert latest[C.YIELD_COLUMN_NAME].iloc[0] == 25.4


def test_new_tenor_appears_and_dead_tenor_disappears(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "n.db")
    old = [_row(t, 20.0, "01/03/2026", "2026-03-01") for t in (91, 182, 700)]
    new = [_row(t, 25.0, "19/11/2026", "2026-11-19") for t in (91, 182, 273, 364, 540)]
    db.save_data(pd.DataFrame(old + new))
    latest, _ = db.load_latest_data()
    tenors = latest[C.TENOR_COLUMN_NAME].tolist()
    assert 540 in tenors  # أجل جديد ظهر تلقائيًا
    assert 700 not in tenors  # أجل بطل ينزل من شهور اختفى
    assert tenors == sorted(tenors)


def test_alert_across_flip_compares_same_bill(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "a.db")
    db.save_data(pd.DataFrame([_row(364, 25.0, "12/11/2026", "2026-11-12")]))
    db.save_data(
        pd.DataFrame(
            [
                _row(357, 26.0, "19/11/2026", "2026-11-19"),
                _row(91, 24.0, "19/11/2026", "2026-11-19"),
            ]
        )
    )
    alerts = db.check_yield_changes(0.5)
    assert [a["tenor"] for a in alerts] == [364]


def test_groups_and_labels():
    assert auction_day_groups([91, 182, 273, 364]) == ([182, 364], [91, 273])
    assert group_label([182, 364]) == "آجال (6 أشهر و 12 شهر)"
    assert group_label([91, 273]) == "آجال (3 أشهر و 9 أشهر)"
    assert active_tenors(pd.DataFrame()) == [91, 182, 273, 364]


def test_364_arriving_after_357_is_latest_and_offered():
    """جلسة 357 (19/11) ثم جلسة 364 (26/11): 364 هو الأحدث وبيظهر للحاسبات."""
    raw = pd.DataFrame(
        {
            C.TENOR_COLUMN_NAME: [91, 182, 273, 357, 364],
            C.YIELD_COLUMN_NAME: [24.9, 25.3, 26.2, 26.165, 26.4],
            C.SESSION_DATE_COLUMN_NAME: ["19/11/2026"] * 4 + ["26/11/2026"],
        }
    )
    df = latest_active_rows(raw)
    assert df[C.TENOR_COLUMN_NAME].tolist() == [91, 182, 273, 364]
    assert df[df[C.TENOR_COLUMN_NAME] == 364][C.YIELD_COLUMN_NAME].iloc[0] == 26.4
    assert active_tenors(raw) == [91, 182, 273, 364]


def test_calculation_uses_actual_days_not_display_tenor():
    """364 معروض لكن آخر جلسة كانت 357 يوم: الحساب بـ 357 مش 364."""
    raw = pd.DataFrame(
        {
            C.TENOR_COLUMN_NAME: [91, 357],
            C.YIELD_COLUMN_NAME: [24.9, 26.165],
            C.SESSION_DATE_COLUMN_NAME: ["19/11/2026"] * 2,
        }
    )
    df = latest_active_rows(raw)
    assert df[C.TENOR_COLUMN_NAME].tolist() == [91, 364]
    assert calc_days(364, df) == 357
    assert calc_days(91, df) == 91
    assert calc_days(364, None) == 364


def test_db_keeps_actual_days_and_exposes_them(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "d.db")
    db.save_data(pd.DataFrame([_row(357, 26.1, "19/11/2026", "2026-11-19")]))
    raw = pd.read_sql_query(f'SELECT * FROM "{C.TABLE_NAME}"', db.engine)
    assert raw[C.TENOR_COLUMN_NAME].tolist() == [357]  # القاعدة ما اتغيرتش
    latest, _ = db.load_latest_data()
    assert latest[C.TENOR_COLUMN_NAME].tolist() == [364]
    assert calc_days(364, latest) == 357
