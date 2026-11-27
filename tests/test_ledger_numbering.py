"""Displayed bill numbers count the bills that exist (1, 2, 3...), not the DB id."""

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine

import ledger
from tests.test_ledger import _row
from ui import portfolio

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 27)


def _rows(ids):
    out = []
    for i in ids:
        r = _row(issue_date=date(2026, 9, 2), maturity_date=date(2026, 12, 2))
        r["id"] = i
        out.append(r)
    return out


def test_numbers_follow_existing_bills_not_db_ids():
    rows = ledger.number_rows(_rows([9, 2, 5]))
    assert {r["id"]: r["no"] for r in rows} == {2: 1, 5: 2, 9: 3}
    # DB ids are untouched
    assert sorted(r["id"] for r in rows) == [2, 5, 9]


def test_single_bill_with_high_db_id_is_number_one():
    rows = ledger.number_rows(_rows([7]))
    assert rows[0]["no"] == 1 and rows[0]["id"] == 7
    assert ledger.number_rows([]) == []


def test_delete_then_add_starts_from_one_and_counts_up():
    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    first = store.add(_row())
    assert portfolio._new_bill_label(store, first) == " (رقم 1)"
    store.delete_row(first)
    assert store.list_all() == []
    second = store.add(_row())
    assert portfolio._new_bill_label(store, second) == " (رقم 1)"
    third = store.add(_row())
    assert portfolio._new_bill_label(store, third) == " (رقم 2)"
    store.delete_row(second)
    # one bill left: it is number 1 even though its DB id is not 1
    rows = ledger.number_rows(store.list_all())
    assert [(r["id"], r["no"]) for r in rows] == [(third, 1)]


def test_new_bill_label_is_empty_when_read_fails():
    class Broken:
        def list_all(self):
            raise RuntimeError("db down")

    assert portfolio._new_bill_label(Broken(), 5) == ""


def test_timeline_alerts_and_csv_use_display_number():
    rows = _rows([4, 8])
    items = {i["id"]: i["no"] for i in ledger.timeline_items(rows, TODAY)}
    assert items == {4: 1, 8: 2}
    alerts = ledger.due_alerts(rows, date(2026, 11, 30))
    assert {a["id"]: a["no"] for a in alerts} == {4: 1, 8: 2}
    text = ledger.alert_text(alerts[1])
    assert "أذن #2 " in text and "#8" not in text
    # alert for the only bill left is #1
    only = ledger.due_alerts(_rows([12]), date(2026, 11, 30))
    assert "أذن #1 " in ledger.alert_text(only[0])


def test_csv_first_column_is_the_display_number():
    r = _row(
        actual_credit_date=date(2026, 11, 24),
        actual_tax_debit=33_864.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=1000.0,
    )
    r["id"] = 41
    ledger.number_rows([r])
    rep = ledger.annual_report([r], 2026)
    lines = ledger.report_to_csv(rep).strip().splitlines()
    assert lines[0].startswith("no,")
    assert lines[1].startswith("1,")


def test_ui_never_shows_the_db_id():
    src = (ROOT / "ui" / "portfolio.py").read_text(encoding="utf-8")
    assert "رقم {new_id}" not in src
    assert "#{sel}" not in src
    assert "#{i['id']}" not in src
    assert "#{i}" not in src
    assert '"#": r["id"]' not in src
    assert "ledger.display_no(" in src
    alert_script = (ROOT / "scripts" / "ledger_maturity_alert.py").read_text(
        encoding="utf-8"
    )
    assert "#{a['id']}" not in alert_script
