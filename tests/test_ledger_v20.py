"""v20: اختبارات الضغط والفشل: دفتر كبير، جلسات، دخول/خروج، قاعدة واقعة، باسورد ناقص، سكريبت التنبيه."""

import os
import re
import sys
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from streamlit.testing.v1 import AppTest

import ledger
import ledger_auth
from tests.test_ledger_v19 import _bill, _with_id

ROOT = os.path.join(os.path.dirname(__file__), "..")
TODAY = date(2026, 11, 27)


def _many(n):
    rows = []
    for i in range(n):
        issue = date(2024, 1, 1) + timedelta(days=i % 900)
        days = (91, 182, 273, 364)[i % 4]
        extra = {}
        if i % 3 == 0:
            extra = dict(
                actual_credit_date=issue + timedelta(days=days),
                actual_tax_debit=100.0,
                actual_purchase_debit=2_800_000.0,
                actual_purchase_debit_date=issue,
                actual_fees=50.0,
            )
        rows.append(_bill(issue, days, **extra))
    return _with_id(rows)


def test_big_ledger_5000_bills_is_fast_and_capped():
    rows = _many(5000)
    t0 = time.time()
    top = ledger.top_summary(rows, TODAY)
    items = ledger.timeline_items(rows, TODAY)
    capped, hidden = ledger.cap_timeline(items)
    ledger.rows_to_csv(rows)
    rep = ledger.annual_report(rows, 2026, None)
    ledger.report_to_csv(rep)
    assert time.time() - t0 < 5
    assert top["open_count"] > 0
    assert len(capped) <= 100 and hidden == 5000 - len(capped)


def test_big_ledger_roundtrip_sqlite_1000_rows():
    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    for r in _many(1000):
        r.pop("id")
        store.add(r)
    t0 = time.time()
    for _ in range(20):  # reruns متكررة
        assert len(store.list_all()) == 1000
    assert time.time() - t0 < 10


def test_cap_timeline_small_ledger_untouched():
    items = ledger.timeline_items(_many(10), TODAY)
    capped, hidden = ledger.cap_timeline(items)
    assert hidden == 0 and len(capped) == 10


def test_global_lockout_across_sessions(monkeypatch):
    monkeypatch.setattr(ledger_auth, "_global_locked_until", 0.0)
    ledger_auth._GLOBAL_FAILS.clear()
    for _ in range(20):
        ledger_auth._record_global_fail()
    assert ledger_auth._globally_locked()
    monkeypatch.setattr(ledger_auth, "_global_locked_until", 0.0)
    assert not ledger_auth._globally_locked()


def test_db_down_fails_fast_and_closed(monkeypatch):
    monkeypatch.setenv("POSTGRES_URI", "postgresql://u:p@127.0.0.1:1/none")
    ledger._ENGINES.clear()
    t0 = time.time()
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.LedgerStore()
    assert time.time() - t0 < 15
    ledger._ENGINES.clear()


def test_no_postgres_uri_is_unavailable_not_local_fallback(monkeypatch):
    monkeypatch.delenv("POSTGRES_URI", raising=False)
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.LedgerStore()


def test_alert_send_failure_is_not_marked_and_retries(capsys):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import ledger_maturity_alert as m

    store = ledger.LedgerStore(engine=create_engine("sqlite://"))
    store.add(_bill(date(2026, 9, 2), 91))
    d = date(2026, 11, 30)
    assert m.run(d, store.list_all(), True, sender=lambda t: False, store=store) == -1
    assert store.list_all()[0]["alerted_on"] is None  # هيتعاد بكره
    assert m.run(d, store.list_all(), True, sender=lambda t: True, store=store) == 1


def test_alert_main_without_db_exits_nonzero_and_sends_nothing(monkeypatch, capsys):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import ledger_maturity_alert as m

    monkeypatch.delenv("POSTGRES_URI", raising=False)
    assert m.main() == 1
    assert "nothing sent" in capsys.readouterr().out


def test_old_table_without_alerted_on_is_upgraded():
    from sqlalchemy import text

    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE tbill_purchases (id INTEGER PRIMARY KEY)"))
    ledger._ENSURED.discard(eng)
    ledger.LedgerStore(engine=eng)
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(tbill_purchases)"))]
    assert "alerted_on" in cols


def test_workflow_step_inside_existing_scrape_job_is_safe():
    p = os.path.join(ROOT, ".github", "workflows", "scheduled_scrape.yml")
    src = open(p, encoding="utf-8").read()
    assert not os.path.exists(
        os.path.join(ROOT, ".github", "workflows", "ledger_maturity_alert.yml")
    )
    i = src.index("Ledger maturity alert")
    step = src[i : src.index("- name:", i + 10)]
    assert "continue-on-error: true" in step
    assert "vars.LEDGER_ALERTS_ENABLED || '0'" in step
    assert set(re.findall(r"secrets\.([A-Z_]+)", step)) == {
        "POSTGRES_URI",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    }
    # بعد جلب البيانات وقبل الـ commit
    assert src.index("python update_data.py") < i < src.index("uses: stefanzweifel")


# ---- جلسات وباسورد (AppTest) ----
def _auth_app():
    import streamlit as st

    import ledger_auth

    if ledger_auth.require_auth("t"):
        st.write("INSIDE")
        if st.button("out", key="out"):
            ledger_auth.logout()
            st.rerun()


def test_missing_password_locks_everything(monkeypatch):
    monkeypatch.delenv("LEDGER_PASSWORD", raising=False)
    at = AppTest.from_function(_auth_app).run()
    assert not at.exception
    assert not any("INSIDE" in m.value for m in at.markdown)
    assert at.error


def test_login_logout_cycles_and_independent_sessions(monkeypatch):
    monkeypatch.setenv("LEDGER_PASSWORD", "pw-test-only")
    monkeypatch.setattr(ledger_auth.time, "sleep", lambda s: None)
    a = AppTest.from_function(_auth_app).run()
    b = AppTest.from_function(_auth_app).run()
    for _ in range(5):
        a.text_input[0].set_value("pw-test-only")
        a.button[0].click().run()
        assert any("INSIDE" in m.value for m in a.markdown), "login failed"
        a.button(key="out").click().run()
        assert not any("INSIDE" in m.value for m in a.markdown)
    assert not any("INSIDE" in m.value for m in b.markdown)  # الجلسة التانية مقفولة
    assert not a.exception and not b.exception


def test_wrong_password_never_enters(monkeypatch):
    monkeypatch.setenv("LEDGER_PASSWORD", "pw-test-only")
    monkeypatch.setattr(ledger_auth.time, "sleep", lambda s: None)
    monkeypatch.setattr(ledger_auth, "_global_locked_until", 0.0)
    ledger_auth._GLOBAL_FAILS.clear()
    at = AppTest.from_function(_auth_app).run()
    for _ in range(7):
        if not at.text_input:  # القفل اشتغل بعد المحاولات الغلط
            break
        at.text_input[0].set_value("nope")
        at.button[0].click().run()
        assert not any("INSIDE" in m.value for m in at.markdown)
    assert not at.text_input and at.error  # مقفول ومفيش نموذج
    assert not at.exception
    ledger_auth._GLOBAL_FAILS.clear()


def test_countdown_text_formats():
    M = 60000
    assert (
        ledger.countdown_text(4 * 1440 * M + 10 * 60 * M + 12 * M)
        == "فاضل 4 يوم 10 س 12 د"
    )
    assert ledger.countdown_text(90 * M) == "فاضل 1 س 30 د"
    assert ledger.countdown_text(5 * M) == "فاضل 5 د"
    assert ledger.countdown_text(-(2 * 1440 + 3 * 60) * M) == "عدّى بـ 2 يوم 3 س"
    assert ledger.countdown_text(-(30) * M) == "عدّى بـ 0 س 30 د"


def test_maturity_epoch_respects_cairo_dst():
    # شتاءً UTC+2 وصيفًا UTC+3 (جدول التوقيت الصيفي المصري)
    from datetime import datetime, timezone

    w = ledger.maturity_epoch_ms(date(2027, 1, 15)) / 1000
    assert (
        datetime.fromtimestamp(w, timezone.utc).hour == 22
    )  # 00:00 القاهرة = 22:00 UTC (+2)
    s = ledger.maturity_epoch_ms(date(2027, 7, 15)) / 1000
    assert datetime.fromtimestamp(s, timezone.utc).hour == 21  # +3


def test_countdown_html_uses_given_now_not_cache():
    t = ledger.maturity_epoch_ms(date(2026, 12, 2))
    h1 = ledger.countdown_html(date(2026, 12, 2), t - 3 * 86400000)
    h2 = ledger.countdown_html(date(2026, 12, 2), t - 3 * 86400000 + 61 * 60000)
    assert "فاضل 3 يوم 0 س 0 د" in h1 and "فاضل 2 يوم 22 س 59 د" in h2
    assert f"data-t='{t}'" in h1


def test_countdown_js_is_single_timer_and_same_format_as_python():
    src = open(os.path.join(ROOT, "ui", "portfolio.py"), encoding="utf-8").read()
    assert src.count("setInterval") == 1 and "clearInterval" in src
    assert "__tbCountdown" in src and "querySelectorAll" in src
