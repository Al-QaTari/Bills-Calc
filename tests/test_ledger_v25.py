from datetime import date

from sqlalchemy import create_engine

import ledger

ALL = "purchase_debit,purchase_debit_date,credit_date,proceeds,tax,fees"


def _row(**kw):
    r = {c: None for c in ledger._LEDGER_COLS}
    r.update(
        id=1,
        face_value=100000.0,
        purchase_price=97000.0,
        gross_return=3000.0,
        tax_amount=600.0,
        issue_date=date(2026, 1, 1),
        maturity_date=date(2026, 4, 1),
        confirmed_fields="",
    )
    r.update(kw)
    return r


def test_new_row_has_nothing_confirmed_even_proceeds():
    r = _row()
    assert ledger.confirmed_fields(r) == set()
    assert not ledger.is_settled(r) and ledger.realized_net(r) is None
    assert ledger.field_status(r, "proceeds", 100000.0) == "estimate"


def test_values_written_but_not_confirmed_do_not_count():
    r = _row(
        actual_credit_date=date(2026, 4, 1),
        actual_tax_debit=600.0,
        actual_purchase_debit=97000.0,
        actual_fees=100.0,
        actual_proceeds=100000.0,
        confirmed_fields="tax",
    )
    assert ledger.confirmed_fields(r) == {"tax"}
    assert not ledger.is_settled(r)
    assert ledger.realized_net(r) is None


def test_profit_only_when_all_required_confirmed():
    r = _row()
    for key, val in [
        ("purchase_debit", 97000.0),
        ("credit_date", date(2026, 4, 1)),
        ("tax", 600.0),
        ("fees", 100.0),
    ]:
        r.update(ledger.confirm_field_update(r, key, val))
        assert ledger.realized_net(r) is None  # proceeds لسه
    assert ledger.is_settled(r)  # التاريخ والضريبة متأكدين
    assert not ledger.all_confirmed(r)
    r.update(ledger.confirm_field_update(r, "proceeds", 100000.0))
    assert ledger.all_confirmed(r)
    assert ledger.realized_net(r) == 100000.0 - 97000.0 - 600.0 - 100.0
    assert ledger.fees_complete(r)


def test_edit_after_confirm_keeps_old_value_until_reconfirmed():
    r = _row(actual_tax_debit=600.0, confirmed_fields="tax")
    assert ledger.field_status(r, "tax", 600.0) == "confirmed"
    assert ledger.field_status(r, "tax", 650.0) == "changed"
    assert r["actual_tax_debit"] == 600.0  # المحفوظ ماتغيرش
    r.update(ledger.confirm_field_update(r, "tax", 650.0))
    assert ledger.field_status(r, "tax", 650.0) == "confirmed"


def test_confirmed_key_without_value_is_ignored():
    r = _row(confirmed_fields="tax,fees")  # القيم نفسها NULL
    assert ledger.confirmed_fields(r) == set()


def test_legacy_row_without_column_still_counts():
    r = _row(
        confirmed_fields=None,
        actual_credit_date=date(2026, 4, 1),
        actual_tax_debit=600.0,
        actual_purchase_debit=97000.0,
        actual_fees=100.0,
    )
    assert ledger.is_settled(r) and ledger.realized_net(r) == 2300.0


def test_store_roundtrip_and_old_table_gets_column():
    eng = create_engine("sqlite://")
    store = ledger.LedgerStore(engine=eng)
    base = {
        k: v
        for k, v in _row().items()
        if k not in ("id", "confirmed_fields") and v is not None
    }
    base.update(
        created_on=date(2026, 1, 1), yield_rate=26.0, tenor_days=91, tax_rate=20.0
    )
    i = store.add(base)
    row = store.list_all()[0]
    assert row["confirmed_fields"] == ""
    store.update_row(i, ledger.confirm_field_update(row, "tax", 600.0))
    row = store.list_all()[0]
    assert ledger.confirmed_fields(row) == {"tax"} and row["actual_tax_debit"] == 600.0
