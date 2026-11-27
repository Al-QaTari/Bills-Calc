"""scrape_date لازم يبقى بداية يوم الجلسة بتوقيت القاهرة (بالـ UTC) زي السكرابر.

الرسم البياني والفلاتر بيقروا العمود ده كتاريخ العطاء. الملء الأول كتبه بوقت التشغيل
فظهرت الصفوف على آخر الرسم بدل مكانها الصح.
"""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

import backfill_history as bf
from tests.test_backfill_history import DB_ROWS, OFFICIAL, _make_sqlite, _run


@pytest.fixture
def official_file(tmp_path):
    p = tmp_path / "official.json"
    p.write_text(json.dumps(OFFICIAL), encoding="utf-8")
    return str(p)


def _scrapes(path):
    with sqlite3.connect(path) as c:
        return {
            (t, s): v
            for t, s, v in c.execute(
                "SELECT tenor, session_date, scrape_date FROM cbe_t_bills"
            )
        }


def test_expected_value_matches_real_snapshot_convention():
    # قيم حقيقية من النسخة: جلسة 07/08/2025 (صيف) و12/11/2026 (شتا)
    assert bf.expected_scrape_utc("07/08/2025") == datetime(
        2025, 8, 6, 21, 0, tzinfo=timezone.utc
    )
    assert bf.expected_scrape_utc("12/11/2026") == datetime(
        2026, 11, 11, 22, 0, tzinfo=timezone.utc
    )


def test_inserted_rows_get_session_day_not_run_time(tmp_path, official_file):
    db = _make_sqlite(tmp_path / "a.db")
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    got = _scrapes(db)
    assert got[(91, "23/08/2026")] == "2026-08-22 21:00:00+00:00"
    assert got[(273, "23/08/2026")] == "2026-08-22 21:00:00+00:00"


def test_repairs_only_rows_saved_with_run_time_and_touches_nothing_else(
    tmp_path, official_file
):
    db = _make_sqlite(tmp_path / "b.db")
    for t, s, _ in DB_ROWS:  # الصفوف العادية: بداية يوم الجلسة (الفرق يوم)
        with sqlite3.connect(db) as c:
            c.execute(
                "UPDATE cbe_t_bills SET scrape_date=? WHERE tenor=? AND session_date=?",
                (bf.expected_scrape_utc(s).strftime("%Y-%m-%d %H:%M:%S+00:00"), t, s),
            )
    with sqlite3.connect(db) as c:  # صفّين اتحفظوا بوقت التشغيل (الغلط القديم)
        c.execute(
            "UPDATE cbe_t_bills SET scrape_date='2026-11-27 16:03:03+00:00' "
            "WHERE session_date IN ('09/08/2026','16/08/2026') AND tenor=91"
        )
    before = _scrapes(db)
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    after = _scrapes(db)
    for key, old in before.items():
        if key in {(91, "09/08/2026"), (91, "16/08/2026")}:
            assert after[key] == bf.expected_scrape_utc(key[1]).strftime(
                "%Y-%m-%d %H:%M:%S+00:00"
            )
        else:
            assert after[key] == old  # مفيش حاجة تانية اتلمست
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    assert _scrapes(db) == after  # التشغيل التاني: ولا تغيير


def test_normal_one_day_offset_is_never_repaired():
    rows = {
        (91, "07/08/2025"): "2025-08-06 21:00:00+00:00",
        (91, "12/11/2026"): "2026-11-11 22:00:00+00:00",
        (91, "13/11/2026"): "2026-11-13 22:00:00+00:00",  # تأخير يوم وراء: مش هيتلمس
    }
    assert bf.plan_scrape_repairs(rows) == []


def test_verify_scrape_dates_detects_collateral_change():
    key = (91, "07/08/2025")
    good = "2025-08-06 21:00:00+00:00"
    assert bf.verify_scrape_dates({key: good}, {key: good}, [], []) == []
    assert bf.verify_scrape_dates(
        {key: good}, {key: "2030-01-01 00:00:00+00:00"}, [], []
    )


# ------------------------------------------------- تصليح العائد القديم (stale)
def _yield_of(path, tenor, session):
    with sqlite3.connect(path) as c:
        return c.execute(
            "SELECT yield FROM cbe_t_bills WHERE tenor=? AND session_date=?",
            (tenor, session),
        ).fetchone()[0]


def test_stale_yield_equal_to_previous_week_is_corrected(
    tmp_path, official_file, capsys
):
    # جلسة 23/08 (إصدار 25/08 الرسمي 23.99) متخزنة بعائد 24.191 = إصدار 18/08 بالظبط
    rows = DB_ROWS + [(91, "23/08/2026", 24.191)]
    db = _make_sqlite(tmp_path / "s.db", rows)
    args = ("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
    assert _run(*args) == 0
    out = capsys.readouterr().out
    assert "24.191% -> 23.99%" in out
    assert _yield_of(db, 91, "23/08/2026") == 23.99
    assert _yield_of(db, 91, "16/08/2026") == 24.191  # الصف الصح ما اتلمسش
    with sqlite3.connect(db) as c:
        (issue,) = c.execute(
            "SELECT issue_date FROM cbe_t_bills WHERE tenor=91 AND session_date='23/08/2026'"
        ).fetchone()
        count = c.execute(
            "SELECT count(*) FROM cbe_t_bills WHERE tenor=91 AND session_date='23/08/2026'"
        ).fetchone()[0]
    assert issue == "25/08/2026" and count == 1  # اتملى إصداره، ومفيش صف مكرر
    assert _run(*args) == 0  # التشغيل التاني: مفيش تغيير تاني
    assert _yield_of(db, 91, "23/08/2026") == 23.99


def test_other_conflicts_are_never_corrected(tmp_path, official_file, monkeypatch):
    monkeypatch.setattr(bf, "MIN_MATCH_RATIO", 0.5)
    rows = DB_ROWS + [(91, "23/08/2026", 20.5)]  # مش عائد الأسبوع اللي قبله
    db = _make_sqlite(tmp_path / "t.db", rows)
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    assert _yield_of(db, 91, "23/08/2026") == 20.5


def test_rule_needs_previous_week_to_differ_from_current(tmp_path):
    official = [
        ["91", "E1", "11/08/2026", "10/11/2026", "1", "1", "1", "1", "1", "24.0"],
        ["91", "E2", "18/08/2026", "17/11/2026", "1", "1", "1", "1", "1", "24.0"],
    ]
    parsed, _ = bf.parse_official_rows(official)
    plan = bf.build_plan(
        parsed,
        [(91, "09/08/2026", 24.0), (91, "16/08/2026", 24.0)],
        bf.date(2026, 8, 1),
        bf.date(2026, 11, 27),
        {},
    )
    bf.plan_stale_fixes(parsed, plan)
    assert plan.stale_fixes == [] and plan.conflicts == []


def test_too_many_stale_fixes_write_nothing(tmp_path, official_file, monkeypatch):
    monkeypatch.setattr(bf, "MAX_STALE_FIXES", 0)
    rows = DB_ROWS + [(91, "23/08/2026", 24.191)]
    db = _make_sqlite(tmp_path / "m.db", rows)
    before = (
        sqlite3.connect(db).execute("SELECT * FROM cbe_t_bills ORDER BY 1,3").fetchall()
    )
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 2
    )
    assert (
        sqlite3.connect(db).execute("SELECT * FROM cbe_t_bills ORDER BY 1,3").fetchall()
        == before
    )


def test_unmatched_rows_are_listed_in_the_log(
    tmp_path, official_file, capsys, monkeypatch
):
    monkeypatch.setattr(bf, "MIN_MATCH_RATIO", 0.5)
    rows = DB_ROWS + [(91, "20/08/2026", 19.0)]
    db = _make_sqlite(tmp_path / "u.db", rows)
    assert _run("--target", f"sqlite:{db}", "--official-json", official_file) == 0
    out = capsys.readouterr().out
    assert "صف مالوش مطابقة رسمية: أجل 91 | جلسة 20/08/2026 | عائد 19.0%" in out


def test_postgres_stale_fix_and_scrape_date_end_to_end(monkeypatch, official_file):
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="pgstale_"))
    try:
        monkeypatch.setenv(
            "POSTGRES_URI", srv.get_uri().replace("postgresql://", "postgres://", 1)
        )
        import postgres_manager as m
        from sqlalchemy import text

        m.dispose_shared_engines()
        db = m.PostgresDBManager()
        rows = DB_ROWS + [(91, "23/08/2026", 24.191)]
        with db.engine.begin() as conn:
            for t, s, y in rows:
                conn.execute(
                    text(
                        "INSERT INTO cbe_t_bills (tenor, yield, session_date, scrape_date) "
                        "VALUES (:t, :y, :s, now())"
                    ),
                    {"t": t, "y": y, "s": s},
                )
        assert _run("--apply", "--official-json", official_file) == 0
        with db.engine.connect() as conn:
            got = conn.execute(
                text(
                    "SELECT yield, issue_date, scrape_date AT TIME ZONE 'UTC' FROM cbe_t_bills "
                    "WHERE tenor=91 AND session_date='23/08/2026'"
                )
            ).fetchone()
            old = conn.execute(
                text(
                    "SELECT scrape_date AT TIME ZONE 'UTC' FROM cbe_t_bills "
                    "WHERE tenor=91 AND session_date='16/08/2026'"
                )
            ).scalar()
        assert abs(got[0] - 23.99) < 1e-4 and got[1] == "25/08/2026"
        assert str(got[2]) == "2026-08-22 21:00:00"
        assert str(old) == "2026-08-15 21:00:00"  # صف قديم اتحفظ بـ now(): اتصلّح كمان
        assert _run("--apply", "--official-json", official_file) == 0
    finally:
        m.dispose_shared_engines()
        srv.cleanup()
