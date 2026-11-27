"""عمود تاريخ الإصدار الرسمي (issue_date): إضافة بس، تعبئة للصف الفاضي، ومطابقة بيه."""

import json
import sqlite3
from datetime import date

import pytest

import backfill_history as bf
import gaps
from tests.test_backfill_history import (  # noqa: F401
    DB_ROWS,
    OFFICIAL,
    SINCE,
    TODAY,
    _dump,
    _make_sqlite,
    _run,
)


@pytest.fixture
def official_file(tmp_path):
    p = tmp_path / "official.json"
    p.write_text(json.dumps(OFFICIAL), encoding="utf-8")
    return str(p)


def _issue_dump(path):
    with sqlite3.connect(path) as c:
        return {
            (t, s): i
            for t, s, i in c.execute(
                "SELECT tenor, session_date, issue_date FROM cbe_t_bills"
            )
        }


def _plan_with_fills(db=DB_ROWS, issue_map=None):
    parsed, _ = bf.parse_official_rows(OFFICIAL)
    plan = bf.build_plan(parsed, db, SINCE, TODAY, issue_map)
    bf.plan_issue_fills(parsed, db, issue_map or {}, plan)
    return plan


def test_fills_match_by_tenor_yield_and_week_including_holiday_shift():
    plan = _plan_with_fills()
    fills = {(f["tenor"], f["session_date"]): f["issue_date"] for f in plan.issue_fills}
    assert fills[(91, "09/08/2026")] == "11/08/2026"
    assert fills[(91, "16/08/2026")] == "18/08/2026"
    # جلسة اتأجلت يوم الاثنين 31/08 لسه بتتربط بإصدار الثلاثاء 01/09 الرسمي
    assert fills[(91, "31/08/2026")] == "01/09/2026"
    assert fills[(182, "30/08/2026")] == "01/09/2026"
    assert plan.issue_ambiguous == []


def test_row_with_stored_issue_is_not_refilled_or_rematched():
    key = (91, "16/08/2026")
    plan = _plan_with_fills(issue_map={key: "18/08/2026"})
    assert all((f["tenor"], f["session_date"]) != key for f in plan.issue_fills)


def test_stored_issue_date_matches_even_if_session_label_is_off():
    # الصف متخزن بجلسة 24/08 (غلط بيوم) لكن إصداره الرسمي 25/08 معروف
    db = [r for r in DB_ROWS if r[:2] != (91, "16/08/2026")] + [
        (91, "24/08/2026", 23.99)
    ]
    plan = _plan_with_fills(db, {(91, "24/08/2026"): "25/08/2026"})
    assert not any(
        r["issue"] == "25/08/2026" and r["tenor"] == 91 for r in plan.to_insert
    )
    assert not any(
        r["issue"] == "25/08/2026" and r["tenor"] == 91 for r in plan.conflicts
    )


def test_stored_issue_with_different_yield_is_a_conflict_not_an_insert():
    db = DB_ROWS + [(91, "24/08/2026", 20.0)]
    plan = _plan_with_fills(db, {(91, "24/08/2026"): "25/08/2026"})
    assert any(c["issue"] == "25/08/2026" and c["tenor"] == 91 for c in plan.conflicts)
    assert not any(
        r["issue"] == "25/08/2026" and r["tenor"] == 91 for r in plan.to_insert
    )


def test_two_rows_claiming_one_issue_are_both_left_empty():
    db = DB_ROWS + [(91, "17/08/2026", 24.191)]  # نفس الأسبوع ونفس العائد
    plan = _plan_with_fills(db)
    filled = {(f["tenor"], f["session_date"]) for f in plan.issue_fills}
    assert (91, "16/08/2026") not in filled and (91, "17/08/2026") not in filled
    amb = {(a["tenor"], a["session_date"]) for a in plan.issue_ambiguous}
    assert {(91, "16/08/2026"), (91, "17/08/2026")} <= amb


def test_unmatched_yield_is_left_empty_not_guessed():
    db = [(t, s, 19.0 if (t, s) == (91, "16/08/2026") else y) for t, s, y in DB_ROWS]
    plan = _plan_with_fills(db)
    assert all(
        (f["tenor"], f["session_date"]) != (91, "16/08/2026") for f in plan.issue_fills
    )
    assert plan.issue_unmatched >= 1


def test_apply_adds_column_fills_and_never_touches_other_values(
    tmp_path, official_file, capsys
):
    db = _make_sqlite(tmp_path / "a.db")
    before = _dump(db)
    assert "issue_date" not in {
        r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(cbe_t_bills)")
    }
    args = ("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
    assert _run(*args) == 0
    after = _dump(db)
    assert set(before) <= set(after)  # الأعمدة القديمة زي ما هي بالحرف
    issues = _issue_dump(db)
    assert issues[(91, "31/08/2026")] == "01/09/2026"
    assert issues[(91, "23/08/2026")] == "25/08/2026"  # الصف الجديد
    assert issues[(273, "23/08/2026")] == "25/08/2026"
    assert all(v for v in issues.values())
    capsys.readouterr()
    assert _run(*args) == 0  # التشغيل التاني: مفيش تغيير
    assert _issue_dump(db) == issues and _dump(db) == after
    assert "لا يوجد ما يُضاف" in capsys.readouterr().out


def test_dry_run_does_not_add_the_column(tmp_path, official_file, capsys):
    db = _make_sqlite(tmp_path / "d.db")
    assert _run("--target", f"sqlite:{db}", "--official-json", official_file) == 0
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(cbe_t_bills)")}
    assert "issue_date" not in cols
    assert "هيتملي لصفوف موجودة" in capsys.readouterr().out


def test_update_never_overwrites_an_existing_issue_date(tmp_path, official_file):
    db = _make_sqlite(tmp_path / "e.db")
    bf.ensure_issue_column(bf.make_engine(f"sqlite:{db}")[0], "sqlite")
    with sqlite3.connect(db) as c:
        c.execute(
            "UPDATE cbe_t_bills SET issue_date='99/99/9999' WHERE tenor=91 AND session_date='16/08/2026'"
        )
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    assert _issue_dump(db)[(91, "16/08/2026")] == "99/99/9999"


def test_verify_issue_dates_detects_problems():
    before = {(91, "a"): "11/08/2026", (91, "b"): None}
    fills = [{"tenor": 91, "session_date": "b", "issue_date": "18/08/2026"}]
    good = {(91, "a"): "11/08/2026", (91, "b"): "18/08/2026"}
    assert bf.verify_issue_dates(before, good, fills, []) == []
    assert bf.verify_issue_dates(before, {**good, (91, "a"): "12/08/2026"}, fills, [])
    assert bf.verify_issue_dates(before, {**good, (91, "b"): None}, fills, [])


def test_gaps_use_issue_date_when_present():
    # جلسة اتخزنت بتاريخ غريب (الأربعاء) لكن إصدارها الرسمي معروف: ما تبقاش فجوة
    rows = [
        (91, "09/08/2026", "11/08/2026"),
        (91, "19/08/2026", "18/08/2026"),
        (91, "23/08/2026", "25/08/2026"),
    ]
    assert gaps.find_session_gaps(rows) == []
    # من غير تاريخ الإصدار نفس الصفوف بتتحسب بالطريقة القديمة (زي الأول)
    assert gaps.find_session_gaps([r[:2] for r in rows]) == gaps.find_session_gaps(
        [(91, "09/08/2026", None), (91, "19/08/2026", None), (91, "23/08/2026", None)]
    )


def test_gaps_still_detect_a_real_missing_week_with_issue_dates():
    rows = [(91, "09/08/2026", "11/08/2026"), (91, "23/08/2026", "25/08/2026")]
    found = gaps.find_session_gaps(rows)
    assert len(found) == 1 and found[0]["missing_dates"] == ["16/08/2026"]


def test_managers_hide_issue_column_from_display_data_and_use_it_for_gaps(tmp_path):
    from db_manager import SQLiteDBManager

    path = _make_sqlite(tmp_path / "m.db")
    bf.ensure_issue_column(bf.make_engine(f"sqlite:{path}")[0], "sqlite")
    with sqlite3.connect(path) as c:
        c.execute(
            "UPDATE cbe_t_bills SET issue_date='11/08/2026' WHERE session_date='09/08/2026'"
        )
    db = SQLiteDBManager(db_filename=path)
    data = db._load_all_historical_data_raw()
    assert "issue_date" not in data.columns and len(data) == len(DB_ROWS)
    assert isinstance(db.detect_data_gaps(), list)


def test_workflow_command_unchanged_and_fills_run_in_it():
    text = open(".github/workflows/scheduled_scrape.yml", encoding="utf-8").read()
    assert "python backfill_history.py --apply --target postgres" in text


def test_odd_tenor_and_nominal_tenor_in_same_week_do_not_collide():
    official = [
        ["336", "EGT1", "03/03/2026", "02/02/2027", "1", "1", "1", "1", "1", "25.0"],
        ["364", "EGT2", "03/03/2026", "02/03/2027", "1", "1", "1", "1", "1", "25.0"],
    ]
    parsed, rejected = bf.parse_official_rows(official)
    assert rejected == []
    db = [(336, "01/03/2026", 25.0), (364, "26/02/2026", 25.0)]
    plan = bf.build_plan(parsed, db, date(2026, 1, 1), TODAY, {})
    bf.plan_issue_fills(parsed, db, {}, plan)
    assert plan.issue_ambiguous == []
    assert {(f["tenor"], f["issue_date"]) for f in plan.issue_fills} == {
        (336, "03/03/2026"),
        (364, "03/03/2026"),
    }
