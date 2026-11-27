"""اختبارات v19: كروت الملخص، الخط الزمني، تنبيه الاستحقاق، وفحص التعارض بين الأقسام."""

import os
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine

import ledger
from tests.test_ledger import _row

TODAY = date(2026, 11, 27)


def _bill(issue, days, **over):
    return _row(
        issue_date=issue,
        tenor_days=days,
        maturity_date=ledger.maturity_from_issue(issue, days),
        **over,
    )


def _with_id(rows):
    return [dict(r, id=i + 1) for i, r in enumerate(rows)]


def test_top_summary_counts_only_open_and_picks_nearest_upcoming():
    rows = _with_id(
        [
            _bill(date(2026, 8, 20), 91),  # استحق من 8 أيام ومن غير كشف
            _bill(date(2026, 9, 2), 91),  # 2026-12-02
            _bill(date(2026, 10, 27), 364),
            _bill(
                date(2026, 2, 24),
                91,
                actual_credit_date=date(2026, 5, 26),
                actual_purchase_debit=2_807_000.0,
                actual_purchase_debit_date=date(2026, 2, 24),
                actual_tax_debit=38_500.0,
                actual_fees=1000.0,
            ),
        ]
    )
    t = ledger.top_summary(rows, TODAY)
    assert t["open_count"] == 3  # المنزّل من الكشف مش مفتوح
    assert t["invested"] == pytest.approx(3 * 2_830_000.0)
    assert t["nearest"]["id"] == 2 and t["nearest_days"] == 5


def test_top_summary_empty():
    t = ledger.top_summary([], TODAY)
    assert t["nearest"] is None and t["invested"] == 0 and t["expected_net"] == 0


def test_timeline_status_colors_and_percent():
    rows = _with_id(
        [
            _bill(date(2026, 9, 2), 91),
            _bill(date(2026, 10, 27), 364),
            _bill(date(2026, 8, 20), 91),
            _bill(
                date(2026, 2, 24),
                91,
                actual_credit_date=date(2026, 5, 26),
                actual_tax_debit=100.0,
            ),
        ]
    )
    items = {i["id"]: i for i in ledger.timeline_items(rows, TODAY)}
    assert items[1]["status"] == ledger.STATUS_NEAR
    assert items[2]["status"] == ledger.STATUS_OPEN
    assert items[3]["status"] == ledger.STATUS_OVERDUE
    assert items[4]["status"] == ledger.STATUS_SETTLED and items[4]["pct"] == 100
    assert 0 <= items[2]["pct"] <= 100
    # المنزّل في آخر القايمة
    assert ledger.timeline_items(rows, TODAY)[-1]["id"] == 4


def test_due_alerts_window_overdue_and_once_per_bill():
    rows = _with_id(
        [
            _bill(date(2026, 9, 2), 91),  # 2026-12-02
            _bill(date(2026, 9, 5), 91),  # 2026-12-05
            _bill(
                date(2026, 9, 3),
                91,
                actual_credit_date=date(2026, 12, 3),
                actual_tax_debit=100.0,
            ),  # منزّل: مايتنبّهش
            _bill(date(2026, 8, 20), 91),  # استحق 2026-11-19 من غير كشف
            _bill(
                date(2026, 9, 2), 91, alerted_on=date(2026, 11, 28)
            ),  # اتنبّه قبل كده
        ]
    )
    ids = lambda d: [a["id"] for a in ledger.due_alerts(rows, d)]  # noqa: E731
    assert ids(date(2026, 11, 27)) == [4]  # 12-02 بعد 5 أيام: برا النافذة (4)
    assert ids(date(2026, 11, 28)) == [4, 1]
    assert ids(date(2026, 12, 1)) == [4, 1, 2]
    assert ids(date(2026, 11, 20)) == [4]  # 12-02 لسه بعيد (12 يوم)
    assert ids(date(2026, 10, 1)) == []
    txt = ledger.alert_text(ledger.due_alerts(rows, date(2026, 11, 27))[0])
    assert "استحق من" in txt and "تقدير" in txt


def test_alert_script_dry_run_does_not_send(capsys):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import ledger_maturity_alert as m

    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    row = _bill(date(2026, 9, 2), 91)
    store.add(row)
    rows = store.list_all()
    sent = []

    def ok(t):
        sent.append(t)
        return True

    d = date(2026, 11, 30)
    assert m.run(d, rows, False, sender=ok, store=store) == 1  # dry-run
    assert sent == [] and "dry-run" in capsys.readouterr().out
    assert store.list_all()[0]["alerted_on"] is None  # مفيش علامة في dry-run
    assert m.run(d, rows, True, sender=ok, store=store) == 1
    assert len(sent) == 1 and store.list_all()[0]["alerted_on"] == d
    # التشغيلة الجاية (بعد 3 أيام): مفيش تكرار
    assert m.run(date(2026, 12, 3), store.list_all(), True, sender=ok, store=store) == 0
    assert len(sent) == 1


def test_send_without_telegram_secrets_returns_false(monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import ledger_maturity_alert as m

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert m.send("x") is False


def test_features_together_on_one_store():
    """حفظ، كروت، خط زمني، تنبيه، CSV، تقرير نصف سنوي، حذف: على نفس الدفتر من غير تعارض."""
    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    for issue, days in [(date(2026, 9, 2), 91), (date(2026, 10, 27), 364)]:
        store.add(_bill(issue, days))
    rows = store.list_all()
    assert ledger.top_summary(rows, TODAY)["open_count"] == 2
    assert len(ledger.timeline_items(rows, TODAY)) == 2
    assert len(ledger.due_alerts(rows, date(2026, 11, 30))) == 1
    assert ledger.rows_to_csv(rows).count("\n") >= 3
    rep = ledger.annual_report(rows, 2026, 2)
    assert (
        rep.count == 0 and len(rep.entered) == 1
    )  # النص التاني 2026 فيه استحقاق 12-02
    assert "2026" in ledger.report_to_csv(rep)
    store.delete_row(rows[0]["id"])
    after = store.list_all()
    assert len(after) == 1
    assert ledger.top_summary(after, TODAY)["open_count"] == 1
    assert ledger.top_summary(after, TODAY)["nearest"]["id"] == after[0]["id"]


def test_ledger_page_isolated_from_calculators_and_admin():
    """الدفتر مايغيّرش الحاسبات: مفيش import من الدفتر في كود الحساب/الأدمن/التنبيهات."""
    root = os.path.join(os.path.dirname(__file__), "..")
    for name in ("calculations.py", "secret_admin_panel.py", "update_data.py"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            src = open(p, encoding="utf-8").read()
            assert "import ledger" not in src and "from ledger" not in src
