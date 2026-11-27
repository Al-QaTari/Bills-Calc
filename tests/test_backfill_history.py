import json
import sqlite3
from datetime import date

import pytest

import backfill_history as bf

# صفوف حقيقية من صفحة البيانات التاريخية الرسمية (بنفس ترتيب الأعمدة)
# المدة، ISIN، الإصدار، الاستحقاق، المطلوب، المقدم، المقبول، أدنى، أعلى، المتوسط المرجح
OFFICIAL = [
    [
        "91",
        "EGT9980ABQ11",
        "11/08/2026",
        "10/11/2026",
        "40,000,000,000",
        "117,988,875,000",
        "43,935,025,000",
        "24.299",
        "24.642",
        "24.631",
    ],
    [
        "91",
        "EGT9980HBQ14",
        "18/08/2026",
        "17/11/2026",
        "35,000,000,000",
        "126,264,825,000",
        "39,791,050,000",
        "24.001",
        "24.24",
        "24.191",
    ],
    [
        "91",
        "EGT9980OBQ15",
        "25/08/2026",
        "24/11/2026",
        "35,000,000,000",
        "72,713,525,000",
        "40,257,950,000",
        "20.999",
        "24.1",
        "23.99",
    ],
    [
        "91",
        "EGT99801CQ13",
        "01/09/2026",
        "01/12/2026",
        "65,000,000,000",
        "90,038,175,000",
        "27,992,075,000",
        "19.998",
        "24.249",
        "24.127",
    ],
    [
        "273",
        "EGT9980B5R19",
        "11/08/2026",
        "11/05/2027",
        "70,000,000,000",
        "201,530,575,000",
        "90,000,000,000",
        "25.501",
        "25.949",
        "25.913",
    ],
    [
        "273",
        "EGT9980I5R14",
        "18/08/2026",
        "18/05/2027",
        "70,000,000,000",
        "193,990,150,000",
        "102,320,950,000",
        "25.391",
        "25.63",
        "25.563",
    ],
    [
        "273",
        "EGT9980P5R19",
        "25/08/2026",
        "25/05/2027",
        "70,000,000,000",
        "183,547,725,000",
        "120,299,125,000",
        "24",
        "25.489",
        "25.443",
    ],
    [
        "273",
        "EGT998016R17",
        "01/09/2026",
        "01/06/2027",
        "75,000,000,000",
        "132,411,525,000",
        "59,421,525,000",
        "25.2",
        "25.651",
        "25.584",
    ],
    [
        "182",
        "EGT998092R14",
        "11/08/2026",
        "09/02/2027",
        "50,000,000,000",
        "180,072,650,000",
        "97,058,450,000",
        "24.790",
        "25.940",
        "25.861",
    ],
    [
        "182",
        "EGT9980G2R11",
        "18/08/2026",
        "16/02/2027",
        "45,000,000,000",
        "221,986,350,000",
        "83,641,800,000",
        "24.499",
        "25.641",
        "25.599",
    ],
    [
        "182",
        "EGT9980N2R17",
        "25/08/2026",
        "23/02/2027",
        "45,000,000,000",
        "193,631,375,000",
        "82,710,550,000",
        "25.2",
        "25.501",
        "25.463",
    ],
    [
        "182",
        "EGT998023R18",
        "01/09/2026",
        "02/03/2027",
        "65,000,000,000",
        "148,459,775,000",
        "60,872,450,000",
        "24.8",
        "25.501",
        "25.461",
    ],
]

# القاعدة كما في النسخة: ناقص عطاء 25/08 (جلسة 23/08) لـ 91 و273
DB_ROWS = [
    (91, "09/08/2026", 24.631),
    (91, "16/08/2026", 24.191),
    (91, "31/08/2026", 24.127),
    (273, "09/08/2026", 25.913),
    (273, "16/08/2026", 25.563),
    (273, "31/08/2026", 25.584),
    (182, "06/08/2026", 25.861),
    (182, "13/08/2026", 25.599),
    (182, "20/08/2026", 25.463),
    (182, "30/08/2026", 25.461),
]
SINCE = date(2026, 8, 1)
TODAY = date(2026, 11, 27)


def _plan(official=None, db=None, since=SINCE, today=TODAY):
    parsed, _ = bf.parse_official_rows(official if official is not None else OFFICIAL)
    return bf.build_plan(parsed, db if db is not None else DB_ROWS, since, today)


# ---------------------------------------------------------------- parsing
def test_parse_reads_weighted_average_not_min_or_max():
    parsed, rejected = bf.parse_official_rows(OFFICIAL)
    assert rejected == []
    by_key = {(a.tenor, a.issue): a for a in parsed}
    # 25/08/2026: أدنى 20.999، أعلى 24.1، المتوسط المرجح 23.99 (هو اللي بيتخزن)
    assert by_key[(91, date(2026, 8, 25))].yield_pct == 23.99
    assert by_key[(273, date(2026, 8, 25))].yield_pct == 25.443


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda r: r[:9], "عدد الأعمدة"),
        (lambda r: r[:9] + ["abc"], "قيمة غير رقمية"),
        (lambda r: ["x"] + r[1:], "قيمة غير رقمية"),
        (lambda r: r[:2] + ["31/02/2026"] + r[3:], "تاريخ غير صالح"),
        (lambda r: r[:9] + ["0"], "عائد غير معقول"),
        (lambda r: r[:9] + ["-3"], "عائد غير معقول"),
        (lambda r: r[:9] + ["60"], "عائد غير معقول"),
        (lambda r: r[:9] + ["2491.7"], "عائد غير معقول"),
        (lambda r: ["92"] + r[1:], "الأجل لا يطابق"),
        (lambda r: ["3"] + r[1:], "أجل غير معقول"),
    ],
)
def test_parse_rejects_bad_rows(mutate, reason):
    parsed, rejected = bf.parse_official_rows([mutate(OFFICIAL[0])])
    assert parsed == []
    assert len(rejected) == 1 and reason in rejected[0][1]


def test_parse_duplicates():
    same = bf.parse_official_rows([OFFICIAL[0], OFFICIAL[0]])
    assert len(same[0]) == 1 and same[1] == []
    other = OFFICIAL[0][:9] + ["24.5"]
    conflict, rejected = bf.parse_official_rows([OFFICIAL[0], other])
    assert conflict == [] and len(rejected) == 1  # مش بنختار واحد من اتنين مختلفين


def test_extract_rows_from_html_keeps_only_data_rows():
    html = """
    <table><tr><th>المدة</th><th>ISIN</th></tr>
    <tr>{}</tr>
    <tr><td>91</td><td>short</td></tr>
    <tr><td>ليس رقم</td>{}</tr></table>
    """.format(
        "".join(f"<td>{c}</td>" for c in OFFICIAL[2]),
        "".join(f"<td>{c}</td>" for c in OFFICIAL[2][1:]),
    )
    assert bf.extract_rows_from_html(html) == [OFFICIAL[2]]


# ------------------------------------------------------- session date rule
def test_infer_session_date():
    assert bf.infer_session_date(91, date(2026, 8, 25)) == (date(2026, 8, 23), "")
    assert bf.infer_session_date(273, date(2026, 8, 25))[0] == date(2026, 8, 23)
    assert bf.infer_session_date(182, date(2026, 8, 25))[0] == date(2026, 8, 20)
    assert bf.infer_session_date(357, date(2026, 8, 25))[0] == date(2026, 8, 20)
    # إصدار مش يوم ثلاثاء: اليوم المتوقع مش أحد، فمش بنخمّن
    session, reason = bf.infer_session_date(91, date(2026, 8, 26))
    assert session is None and reason
    assert bf.infer_session_date(40, date(2026, 8, 25))[0] is None


# ------------------------------------------------------------------- plan
def test_plan_finds_exactly_the_missing_rows():
    plan = _plan()
    assert plan.already_present == 10
    assert [(r["tenor"], r["session_date"], r["yield"]) for r in plan.to_insert] == [
        (91, "23/08/2026", 23.99),
        (273, "23/08/2026", 25.443),
    ]
    assert plan.conflicts == [] and plan.needs_review == []


def test_plan_accepts_session_stored_on_issue_date():
    db = [r for r in DB_ROWS if not (r[0] == 91 and r[1] == "16/08/2026")]
    db.append((91, "18/08/2026", 24.191))  # الصف متخزن بتاريخ الإصدار (الثلاثاء)
    plan = _plan(db=db)
    assert (91, "16/08/2026") not in [
        (r["tenor"], r["session_date"]) for r in plan.to_insert
    ]
    assert plan.already_present == 10


def test_plan_does_not_confuse_previous_weeks_tuesday_row():
    # صف الأسبوع اللي فات متخزن يوم الثلاثاء 18/08: مايتحسبش لأسبوع 25/08
    db = [r for r in DB_ROWS if r[0] != 91] + [(91, "18/08/2026", 24.191)]
    plan = _plan(db=db)
    inserted_91 = [r["issue"] for r in plan.to_insert if r["tenor"] == 91]
    assert "25/08/2026" in inserted_91


def test_plan_conflict_is_reported_and_never_inserted():
    db = [(t, s, 25.0 if (t, s) == (91, "16/08/2026") else y) for t, s, y in DB_ROWS]
    plan = _plan(db=db)
    assert len(plan.conflicts) == 1
    conflict = plan.conflicts[0]
    assert conflict["db_yield"] == 25.0 and conflict["yield"] == 24.191
    assert all(r["issue"] != "18/08/2026" or r["tenor"] != 91 for r in plan.to_insert)


def test_plan_yield_tolerance():
    db = [(t, s, y + 0.0004) for t, s, y in DB_ROWS]  # REAL في PostgreSQL بيقرّب
    assert _plan(db=db).already_present == 10
    db = [(t, s, y + 0.002) for t, s, y in DB_ROWS]
    assert len(_plan(db=db).conflicts) == 10


def test_plan_skips_rows_before_since_and_future_sessions():
    plan = _plan(since=date(2026, 8, 25))  # الإصدار 25/08 وقبله مستبعد
    assert plan.skipped_old == 9
    assert plan.to_insert == []
    plan = _plan(today=date(2026, 8, 22))  # جلسة 23/08 لسه في المستقبل
    assert plan.skipped_future == 2 and plan.to_insert == []


def test_plan_needs_review_when_weekday_is_unexpected_or_slot_taken():
    odd = ["91", "EGT9980OBQ15", "26/08/2026", "25/11/2026"] + OFFICIAL[2][4:]
    plan = _plan(official=OFFICIAL + [odd])
    assert [r["issue"] for r in plan.needs_review] == ["26/08/2026"]
    # نفس الجلسة موجودة بعائد مختلف خارج نافذة الإصدار: بنوقف ومنكتبش فوقها
    db = DB_ROWS + [(91, "23/08/2026", 20.0)]
    plan = _plan(db=db)
    assert len(plan.conflicts) >= 1
    assert all(
        (r["tenor"], r["session_date"]) != (91, "23/08/2026") for r in plan.to_insert
    )


def test_plan_odd_tenor_matches_its_nominal_family():
    # أذن 357 يوم (إصدار ثلاثاء، جلسة خميس) متخزن 364 في القاعدة: مش ناقص
    official = [
        ["357", "EGTX", "25/08/2026", "17/08/2027", "1", "1", "1", "24", "25", "25.463"]
    ]
    plan = _plan(official=official, db=[(364, "20/08/2026", 25.463)])
    assert plan.already_present == 1 and plan.to_insert == []


# ------------------------------------------------------------ sanity guard
def test_sanity_guard():
    plan = _plan()
    bf.check_plan_is_sane(plan, parsed_count=12, rejected_count=0)
    with pytest.raises(RuntimeError):
        bf.check_plan_is_sane(plan, 0, 0)
    with pytest.raises(RuntimeError):
        bf.check_plan_is_sane(plan, 12, 5)  # صفوف مرفوضة كتير: الصفحة اتغيرت
    unrelated = _plan(db=[(91, "01/01/2020", 10.0)])
    with pytest.raises(RuntimeError):
        bf.check_plan_is_sane(unrelated, 12, 0)  # القاعدة مش شبه الصفحة


def test_verify_after_apply_detects_changes():
    before = [(91, "16/08/2026", 24.191)]
    new = [{"tenor": 91, "session_date": "23/08/2026", "yield": 23.99}]
    good = before + [(91, "23/08/2026", 23.99)]
    assert bf.verify_after_apply(before, good, new) == []
    assert bf.verify_after_apply(before, [(91, "16/08/2026", 24.2)] + good[1:], new)
    assert bf.verify_after_apply(before, good[1:], new)
    assert bf.verify_after_apply(before, before, new)


# ------------------------------------------------------------- end to end
def _make_sqlite(path, rows=DB_ROWS):
    from db_manager import SQLiteDBManager

    SQLiteDBManager(db_filename=path)
    with sqlite3.connect(path) as c:
        c.executemany(
            "INSERT INTO cbe_t_bills (tenor, yield, session_date, scrape_date) VALUES (?,?,?,?)",
            [(t, y, s, "2026-01-01 00:00:00+00:00") for t, s, y in rows],
        )
    return str(path)


def _dump(path):
    with sqlite3.connect(path) as c:
        return sorted(
            c.execute("SELECT tenor, yield, session_date, scrape_date FROM cbe_t_bills")
        )


@pytest.fixture
def official_file(tmp_path):
    p = tmp_path / "official.json"
    p.write_text(json.dumps(OFFICIAL), encoding="utf-8")
    return str(p)


def _run(*args):
    return bf.main(list(args))


def test_dry_run_changes_nothing(tmp_path, official_file, capsys):
    db = _make_sqlite(tmp_path / "a.db")
    before = _dump(db)
    assert _run("--target", f"sqlite:{db}", "--official-json", official_file) == 0
    assert _dump(db) == before
    out = capsys.readouterr().out
    assert "dry-run" in out and "23/08/2026" in out


def test_apply_adds_only_missing_rows_and_is_idempotent(
    tmp_path, official_file, capsys
):
    db = _make_sqlite(tmp_path / "a.db")
    before = _dump(db)
    args = ("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
    assert _run(*args) == 0
    after = _dump(db)
    assert len(after) == len(before) + 2
    assert set(before) <= set(
        after
    )  # الصفوف القديمة زي ما هي بالحرف (بما فيها scrape_date)
    added = sorted(set(after) - set(before))
    assert [(t, y, s) for t, y, s, _ in added] == [
        (91, 23.99, "23/08/2026"),
        (273, 25.443, "23/08/2026"),
    ]
    assert all(row[3].endswith("+00:00") for row in added)
    capsys.readouterr()
    assert _run(*args) == 0  # التشغيل التاني: مفيش حاجة تتضاف
    assert _dump(db) == after
    assert "لا يوجد ما يُضاف" in capsys.readouterr().out


def test_apply_never_overwrites_a_conflicting_row(tmp_path, official_file, monkeypatch):
    monkeypatch.setattr(bf, "MIN_MATCH_RATIO", 0.5)  # العينة صغيرة (12 صف)
    rows = [(t, s, 25.0 if (t, s) == (91, "16/08/2026") else y) for t, s, y in DB_ROWS]
    db = _make_sqlite(tmp_path / "c.db", rows)
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 0
    )
    with sqlite3.connect(db) as c:
        (value,) = c.execute(
            "SELECT yield FROM cbe_t_bills WHERE tenor=91 AND session_date='16/08/2026'"
        ).fetchone()
    assert value == 25.0


def test_max_insert_guard_writes_nothing(tmp_path, official_file):
    db = _make_sqlite(tmp_path / "m.db")
    before = _dump(db)
    code = _run(
        "--apply",
        "--max-insert",
        "1",
        "--target",
        f"sqlite:{db}",
        "--official-json",
        official_file,
    )
    assert code == 2 and _dump(db) == before


def test_garbage_page_writes_nothing(tmp_path):
    db = _make_sqlite(tmp_path / "g.db")
    before = _dump(db)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([["x"] * 10 for _ in range(30)]), encoding="utf-8")
    code = _run("--apply", "--target", f"sqlite:{db}", "--official-json", str(bad))
    assert code == 2 and _dump(db) == before
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    code = _run("--apply", "--target", f"sqlite:{db}", "--official-json", str(empty))
    assert code == 2 and _dump(db) == before


def test_page_down_does_not_fail_and_writes_nothing(tmp_path, monkeypatch, capsys):
    db = _make_sqlite(tmp_path / "d.db")
    before = _dump(db)

    async def boom(*_a, **_k):
        raise bf.FetchError("TimeoutError: page down")

    monkeypatch.setattr(bf, "fetch_official_rows", boom)
    assert _run("--apply", "--target", f"sqlite:{db}") == 0
    assert _dump(db) == before
    assert "غير متاحة" in capsys.readouterr().out


def test_no_silent_fallback_without_postgres_uri(monkeypatch, tmp_path, official_file):
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    assert _run("--apply", "--official-json", official_file) == 2
    assert (
        _run(
            "--apply",
            "--target",
            f"sqlite:{tmp_path / 'nope.db'}",
            "--official-json",
            official_file,
        )
        == 2
    )


def test_one_target_failing_does_not_block_the_other(
    tmp_path, monkeypatch, official_file
):
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    db = _make_sqlite(tmp_path / "t.db")
    code = _run(
        "--apply",
        "--target",
        "postgres",
        "--target",
        f"sqlite:{db}",
        "--official-json",
        official_file,
    )
    assert code == 1  # بوستجرس فشل (بلغ بكود 1) والـ SQLite اتنفّذ
    assert len(_dump(db)) == len(DB_ROWS) + 2


def test_empty_table_is_refused(tmp_path, official_file):
    db = _make_sqlite(tmp_path / "e.db", rows=[])
    assert (
        _run("--apply", "--target", f"sqlite:{db}", "--official-json", official_file)
        == 2
    )


def test_postgres_end_to_end(monkeypatch, official_file):
    pgserver = pytest.importorskip("pgserver")
    import tempfile

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="pgbackfill_"))
    try:
        monkeypatch.setenv(
            "POSTGRES_URI", srv.get_uri().replace("postgresql://", "postgres://", 1)
        )
        import postgres_manager as m
        from sqlalchemy import text

        m.dispose_shared_engines()
        db = m.PostgresDBManager()
        with db.engine.begin() as conn:
            for t, s, y in DB_ROWS:
                conn.execute(
                    text(
                        "INSERT INTO cbe_t_bills (tenor, yield, session_date, scrape_date) "
                        "VALUES (:t, :y, :s, '2026-01-01 00:00:00+00')"
                    ),
                    {"t": t, "y": y, "s": s},
                )

        def dump():
            with db.engine.connect() as conn:
                return sorted(
                    conn.execute(
                        text(
                            "SELECT tenor, yield, session_date, scrape_date FROM cbe_t_bills"
                        )
                    ).fetchall()
                )

        before = dump()
        assert _run("--official-json", official_file) == 0  # تجربة: مفيش كتابة
        assert dump() == before
        assert _run("--apply", "--official-json", official_file) == 0
        after = dump()
        assert len(after) == len(before) + 2 and set(before) <= set(after)
        assert (
            _run("--apply", "--official-json", official_file) == 0
        )  # مرة تانية: ولا صف
        assert dump() == after
        with db.engine.connect() as conn:
            empty = conn.execute(
                text("SELECT count(*) FROM cbe_t_bills WHERE issue_date IS NULL")
            ).scalar()
        assert empty == 0  # العمود اتضاف واتملى لكل الصفوف
        assert db.detect_data_gaps() == [] or all(
            g["missing_dates"] != ["23/08/2026"] for g in db.detect_data_gaps()
        )
    finally:
        m.dispose_shared_engines()
        srv.cleanup()
