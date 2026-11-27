from datetime import date

import pytest
from sqlalchemy import create_engine

import ledger


def _row(**over):
    base = dict(
        face_value=3_000_000.0,
        yield_rate=25.0,
        tenor_days=91,
        tax_rate=20.0,
        purchase_price=2_830_000.0,
        gross_return=170_000.0,
        tax_amount=34_000.0,
        issue_date=date(2026, 8, 25),
        maturity_date=date(2026, 11, 24),
        purchase_fee=None,
        redemption_fee=1000.0,
        custody_fee=None,
        fees_confirmed=False,
        actual_purchase_debit_date=None,
        actual_purchase_debit=None,
        actual_credit_date=None,
        actual_tax_debit=None,
        actual_fees=None,
        created_on=date(2026, 8, 25),
    )
    base.update(over)
    return base


def test_redemption_fee_is_capped():
    assert ledger.estimate_redemption_fee(3_000_000) == 1000.0
    assert ledger.estimate_redemption_fee(500_000) == 500.0


def test_maturity_from_issue():
    assert ledger.maturity_from_issue(date(2026, 12, 1), 182) == date(2027, 6, 1)
    assert ledger.maturity_from_issue(date(2026, 12, 1), 364) == date(2027, 11, 30)


def test_unknown_fee_is_not_zero_and_expected_net():
    r = _row()
    assert r["purchase_fee"] is None
    assert ledger.known_fees_total(r) == 1000.0
    assert ledger.expected_net(r) == 170_000 - 34_000 - 1000
    assert not ledger.fees_complete(r)


def test_realized_needs_statement_numbers():
    assert ledger.realized_net(_row()) is None
    r = _row(
        actual_credit_date=date(2026, 11, 24),
        actual_tax_debit=33_864.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=1000.0,
    )
    assert ledger.realized_net(r) == pytest.approx(
        3_000_000 - 2_830_000 - 33_864 - 1000
    )
    r2 = dict(r, actual_fees=None)
    assert ledger.realized_net(r2) is None


def test_store_roundtrip_and_summary():
    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    i = store.add(_row())
    rows = store.list_all()
    assert rows[0]["id"] == i and rows[0]["purchase_fee"] is None
    # من v25: الرقم مابيتحسبش من الكشف إلا بعد تأكيده واحد واحد
    for key, val in [
        ("credit_date", date(2026, 11, 24)),
        ("tax", 33_864.0),
        ("purchase_debit", 2_830_000.0),
        ("proceeds", 3_000_000.0),
        ("fees", 1000.0),
    ]:
        store.update_row(i, ledger.confirm_field_update(store.list_all()[0], key, val))
    s = ledger.summarize(store.list_all(), date(2026, 11, 27))
    assert s.open_count == 0
    assert 2026 in s.realized_net_by_year
    store.delete_row(i)
    assert store.list_all() == []


def test_fails_closed_without_postgres(monkeypatch):
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.LedgerStore()


def test_annual_report_totals():
    r = _row(
        actual_credit_date=date(2026, 11, 24),
        actual_tax_debit=33_864.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=1000.0,
    )
    s = ledger.summarize([r], date(2026, 11, 27))
    d = s.realized_report_by_year[2026]
    assert d["gross"] == 170_000 and d["tax"] == 33_864 and d["fees"] == 1000
    assert d["net"] == pytest.approx(170_000 - 33_864 - 1000)


def test_annual_report_spanning_years():
    # اتشترى 2026 واستحق 2027: بيتحسب في 2027 (تاريخ الاستحقاق)
    done = _row(
        issue_date=date(2026, 8, 25),
        maturity_date=date(2027, 1, 3),
        actual_credit_date=date(2027, 1, 5),
        actual_tax_debit=100.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=1000.0,
    )
    still_open = _row(issue_date=date(2026, 10, 1), maturity_date=date(2027, 4, 1))
    r26 = ledger.annual_report([done, still_open], 2026)
    r27 = ledger.annual_report([done, still_open], 2027)
    assert len(r26.entered) == 0 and r26.count == 0
    assert len(r27.entered) == 2 and r27.count == 1 and len(r27.open_from_year) == 1
    assert r27.net == pytest.approx(170_000 - 100 - 1000)


@pytest.mark.parametrize("days", [91, 182, 273, 364])
def test_all_four_tenors_store_and_timeline(days):
    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    issue = date(2026, 12, 1)
    store.add(
        _row(
            tenor_days=days,
            issue_date=issue,
            maturity_date=ledger.maturity_from_issue(issue, days),
        )
    )
    r = store.list_all()[0]
    assert r["tenor_days"] == days
    tl = ledger.expected_timeline(r)
    assert [t["item"] for t in tl][-1] == "خصم مصاريف أوراق مالية"
    assert tl[1]["date"] == ledger.maturity_from_issue(issue, days)
    assert tl[-1]["date"] == tl[1]["date"] + (date(2026, 1, 2) - date(2026, 1, 1))


def test_sold_bill_expected_net_and_realized_with_proceeds():
    r = _row(sold_on=date(2026, 10, 1), sale_net=150_000.0, custody_fee=100.0)
    assert ledger.is_sold(r) and ledger.expected_net(r) == 149_900.0
    r.update(
        actual_credit_date=date(2026, 10, 1),
        actual_tax_debit=10_000.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=100.0,
        actual_proceeds=2_990_000.0,
    )
    assert ledger.realized_net(r) == pytest.approx(2_990_000 - 2_830_000 - 10_000 - 100)


def test_purchase_fee_estimate_capped():
    assert ledger.estimate_purchase_fee(3_000_000) == 75.0
    assert ledger.estimate_purchase_fee(100_000) == 2.5
    assert ledger.estimate_purchase_fee(1_000_000_000) == 1000.0


def test_fee_estimates_total_and_custody_monthly():
    f = ledger.fee_estimates(3_000_000, 91)
    assert f["purchase"] == 75.0 and f["redemption"] == 1000.0
    assert f["total"] == pytest.approx(f["purchase"] + f["redemption"] + f["custody"])
    assert ledger.custody_monthly(3_000_000) == 50.0


def test_csv_exports():
    done = _row(
        actual_credit_date=date(2026, 11, 24),
        actual_tax_debit=33_864.0,
        actual_purchase_debit=2_830_000.0,
        actual_fees=1000.0,
        id=1,
    )
    open_row = _row(id=2)
    text = ledger.rows_to_csv([done, open_row])
    lines = text.strip().splitlines()
    assert len(lines) == 3 and lines[0].startswith("id,")
    assert "purchase_fee" in lines[0]
    rep = ledger.annual_report([done, open_row], 2026)
    out = ledger.report_to_csv(rep).strip().splitlines()
    assert out[-1].startswith("total 2026,1,")


def test_half_year_reports_by_maturity_date():
    def settled(i, maturity):
        return _row(
            id=i,
            maturity_date=maturity,
            actual_credit_date=maturity,
            actual_tax_debit=100.0,
            actual_purchase_debit=2_830_000.0,
            actual_fees=1000.0,
            issue_date=date(2026, 1, 5),
        )

    rows = [
        settled(1, date(2026, 3, 1)),
        settled(2, date(2026, 9, 1)),
        settled(3, date(2027, 2, 1)),
    ]
    h1 = ledger.annual_report(rows, 2026, 1)
    h2 = ledger.annual_report(rows, 2026, 2)
    full = ledger.annual_report(rows, 2026)
    assert (h1.count, h2.count, full.count) == (1, 1, 2)
    assert h1.net + h2.net == pytest.approx(full.net)
    assert (
        ledger.report_to_csv(h2).strip().splitlines()[-1].startswith("total 2026 H2,")
    )


def test_sold_bill_counts_in_sale_period():
    r = _row(
        maturity_date=date(2027, 5, 1),
        sold_on=date(2026, 10, 1),
        sale_net=1.0,
    )
    assert ledger.period_date(r) == date(2026, 10, 1)
