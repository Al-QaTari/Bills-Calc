import sqlite3
from datetime import date

import pytest

import gaps
from gaps import find_session_gaps, issue_tuesday


def _sun(d, m, y=2026, tenor=91):
    return (tenor, f"{d:02d}/{m:02d}/{y}")


def test_normal_weekly_pattern_has_no_gaps():
    rows = [
        (91, "02/08/2026"),
        (91, "09/08/2026"),
        (91, "16/08/2026"),
        (182, "06/08/2026"),
        (182, "13/08/2026"),
        (182, "20/08/2026"),
    ]
    assert find_session_gaps(rows) == []


def test_old_counter_false_alarm_is_gone():
    # الأحد ثم الخميس: الكاشف القديم كان يعدّ الاثنين والثلاثاء والأربعاء كأيام مفقودة
    rows = [(91, "02/08/2026"), (182, "06/08/2026"), (91, "09/08/2026")]
    assert find_session_gaps(rows) == []


def test_missing_week_is_reported_with_expected_session_date():
    rows = [
        (91, "16/08/2026"),
        (91, "31/08/2026"),
        (273, "16/08/2026"),
        (273, "31/08/2026"),
    ]
    result = find_session_gaps(rows)
    assert len(result) == 1
    gap = result[0]
    assert gap["missing_dates"] == ["23/08/2026"]
    assert gap["gap_length"] == 1
    assert gap["tenor_family"] == "91/273"
    assert gap["start_date"] == "16/08/2026" and gap["end_date"] == "31/08/2026"


def test_two_missing_weeks_and_thursday_family():
    rows = [(182, "06/08/2026"), (364, "27/08/2026")]
    result = find_session_gaps(rows)
    assert result[0]["missing_dates"] == ["13/08/2026", "20/08/2026"]
    assert result[0]["gap_length"] == 2
    assert result[0]["tenor_family"] == "182/364"


def test_holiday_shifts_inside_the_same_issue_week_are_not_gaps():
    rows = [
        (182, "28/08/2025"),  # الخميس (إصدار 2/9)
        (182, "07/09/2025"),  # جلسة الخميس 4/9 اتأجلت للأحد (إصدار 9/9)
        (182, "11/09/2025"),  # الخميس (إصدار 16/9)
        (91, "31/08/2026"),  # الاثنين بدل الأحد
        (91, "06/09/2026"),
    ]
    assert find_session_gaps(rows) == []


def test_session_stored_on_issue_tuesday_is_not_a_gap():
    rows = [(91, "22/03/2026"), (91, "24/03/2026"), (91, "29/03/2026")]
    # 22/03 و24/03 في نفس أسبوع الإصدار (24/03)، و29/03 في الأسبوع اللي بعده
    assert find_session_gaps(rows) == []


def test_other_tenors_and_bad_dates_are_ignored():
    rows = [(30, "01/01/2026"), (91, "not a date"), (91, None), (91, "02/08/2026")]
    assert find_session_gaps(rows) == []
    assert find_session_gaps([]) == []


def test_odd_tenor_counts_with_its_family():
    # 357 بيتوحد لـ 364 (الخميس)
    rows = [(357, "06/08/2026"), (364, "20/08/2026")]
    assert find_session_gaps(rows)[0]["missing_dates"] == ["13/08/2026"]


def test_issue_tuesday():
    assert issue_tuesday(date(2026, 8, 23)) == date(2026, 8, 25)  # الأحد
    assert issue_tuesday(date(2026, 8, 20)) == date(2026, 8, 25)  # الخميس
    assert issue_tuesday(date(2026, 8, 25)) == date(2026, 8, 25)  # الثلاثاء نفسه
    assert issue_tuesday(date(2026, 8, 26)) == date(2026, 9, 1)  # الأربعاء


def test_constants_are_consistent():
    for tenor, weekday in gaps.SESSION_WEEKDAY_BY_TENOR.items():
        assert (1 - weekday) % 7 == gaps.ISSUE_OFFSET_DAYS_BY_TENOR[tenor]


def test_sqlite_manager_uses_new_detector(tmp_path):
    from db_manager import SQLiteDBManager

    db = SQLiteDBManager(db_filename=tmp_path / "g.db")
    with sqlite3.connect(tmp_path / "g.db") as c:
        c.executemany(
            "INSERT INTO cbe_t_bills (tenor, yield, session_date, scrape_date) VALUES (?,?,?,?)",
            [
                (91, 24.0, "16/08/2026", "2026-08-16 00:00:00+00:00"),
                (91, 24.1, "31/08/2026", "2026-08-31 00:00:00+00:00"),
                (182, 25.0, "20/08/2026", "2026-08-20 00:00:00+00:00"),
            ],
        )
    found = db.detect_data_gaps()
    assert [g["missing_dates"] for g in found] == [["23/08/2026"]]


def test_postgres_manager_uses_new_detector(monkeypatch):
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="pggaps_"))
    try:
        monkeypatch.setenv(
            "POSTGRES_URI", srv.get_uri().replace("postgresql://", "postgres://", 1)
        )
        import postgres_manager as m
        from sqlalchemy import text

        m.dispose_shared_engines()
        db = m.PostgresDBManager()
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO cbe_t_bills (tenor, yield, session_date, scrape_date) VALUES "
                    "(91, 24.0, '16/08/2026', now()), (91, 24.1, '31/08/2026', now())"
                )
            )
        assert [g["missing_dates"] for g in db.detect_data_gaps()] == [["23/08/2026"]]
    finally:
        m.dispose_shared_engines()
        srv.cleanup()
