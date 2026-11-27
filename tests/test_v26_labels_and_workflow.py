from datetime import date
from pathlib import Path

import pandas as pd

import ledger
import market_compare as mc


def _sessions(rows):
    return mc.prepare_sessions(
        pd.DataFrame(
            {
                "tenor": [r[0] for r in rows],
                "yield": [r[1] for r in rows],
                "session_date": [r[2] for r in rows],
            }
        )
    )


def test_market_line_warns_when_the_issue_week_session_is_missing():
    # عطاء 23/08 ناقص: أقرب عطاء قبل إصدار 25/08 هو 16/08 (فرق 9 أيام)
    s = _sessions([(91, 24.191, "16/08/2026")])
    cmp_ = mc.compare_bill(s, 91, 23.99, date(2026, 8, 25))
    line = mc.bill_line(cmp_)
    assert cmp_["gap_days"] == 9
    assert "⚠️" in line and "9 يوم" in line and "تقدير" in line


def test_market_line_has_no_warning_for_a_normal_gap():
    s = _sessions([(91, 23.99, "23/08/2026")])
    cmp_ = mc.compare_bill(s, 91, 23.99, date(2026, 8, 25))
    assert cmp_["gap_days"] == 2
    assert "⚠️" not in mc.bill_line(cmp_)
    s = _sessions([(182, 25.463, "20/08/2026")])
    assert "⚠️" not in mc.bill_line(mc.compare_bill(s, 182, 25.4, date(2026, 8, 25)))


def _open(**kw):
    r = {c: None for c in ledger._LEDGER_COLS}
    r.update(
        id=1,
        face_value=3_000_000.0,
        yield_rate=24.0,
        tenor_days=91,
        tax_rate=20.0,
        purchase_price=2_830_680.0,
        gross_return=169_320.0,
        tax_amount=33_864.0,
        issue_date=date(2026, 8, 25),
        maturity_date=date(2026, 11, 24),
        confirmed_fields="",
    )
    r.update(kw)
    return r


def test_top_summary_counts_confirmed_purchase_amounts():
    rows = [_open(id=1, actual_purchase_debit=2_830_680.0), _open(id=2)]
    top = ledger.top_summary(rows, date(2026, 9, 1))
    assert top["open_count"] == 2 and top["invested_confirmed_count"] == 1
    assert ledger.top_summary([], date(2026, 9, 1))["invested_confirmed_count"] == 0


def _workflow_steps(text):
    """قسّم الـ workflow لخطوات بالنص (من غير مكتبة yaml، مش موجودة في بيئة الـ CI)."""
    steps, current = [], None
    for line in text.splitlines():
        if line.startswith("      - name:"):
            current = {"name": line.split(":", 1)[1].strip(), "body": []}
            steps.append(current)
        elif current is not None and not line.startswith("      #"):
            current["body"].append(line)
    for step in steps:
        step["text"] = "\n".join(step["body"])
    return steps


def test_scheduled_workflow_runs_backfill_insert_only_and_never_fails_the_scrape():
    path = (
        Path(__file__).resolve().parent.parent
        / ".github/workflows/scheduled_scrape.yml"
    )
    steps = _workflow_steps(path.read_text(encoding="utf-8"))
    names = [s["name"] for s in steps]
    index = next(i for i, s in enumerate(steps) if "backfill_history.py" in s["text"])
    step = steps[index]["text"]
    assert "continue-on-error: true" in step
    assert "--apply" in step and "sqlite:data/cbe_historical_data.db" in step
    assert "POSTGRES_URI: ${{ secrets.POSTGRES_URI }}" in step
    # بعد التحديث وقبل الـ commit اللي بيحفظ نسخة SQLite
    assert names.index("Run data update script") < index
    assert index < names.index("Commit and push if data changed")
