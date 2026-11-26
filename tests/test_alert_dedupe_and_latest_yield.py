"""تنبيهات تليجرام لا تتكرر + عائد "أحدث عائد متاح" يتغير فعلاً في الحقل."""

from pathlib import Path

import pandas as pd

import constants as C
from db_manager import SQLiteDBManager
import update_data as u


def _rows(items):
    return pd.DataFrame(
        [
            {
                C.TENOR_COLUMN_NAME: t,
                C.YIELD_COLUMN_NAME: y,
                C.SESSION_DATE_COLUMN_NAME: s,
                C.DATE_COLUMN_NAME: pd.to_datetime("2026-01-01"),
            }
            for t, y, s in items
        ]
    )


def test_retired_tenor_gives_no_alert(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "a.db")
    db.save_data(
        _rows(
            [
                (91, 24.0, "01/11/2026"),
                (91, 25.0, "08/11/2026"),
                (int("3" + "36"), 23.2, "01/03/2026"),
                (int("3" + "36"), 23.4, "08/03/2026"),
            ]
        )
    )
    assert [a["tenor"] for a in db.check_yield_changes(0.5)] == [91]


def test_sent_alert_not_resent_even_with_fresh_cache_file(tmp_path):
    db = SQLiteDBManager(db_filename=tmp_path / "b.db")
    db.save_data(_rows([(91, 24.0, "01/11/2026"), (91, 25.0, "08/11/2026")]))
    alerts = db.check_yield_changes(0.5)
    assert alerts
    first = u.AlertManager(cache_file=tmp_path / "c1.json", engine=db.engine)
    assert not first.is_duplicate(alerts[0])
    first.mark_sent(alerts[0])
    # تشغيل جديد (ملف كاش جديد، مثل GitHub Actions) يجب ألا يعيد الإرسال
    second = u.AlertManager(cache_file=tmp_path / "c2.json", engine=db.engine)
    assert second.is_duplicate(alerts[0])


def test_use_latest_updates_yield_field():
    from streamlit.testing.v1 import AppTest

    script = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
import streamlit as st, pandas as pd
import constants as C
from state_manager import StateManager
df = pd.DataFrame({{C.TENOR_COLUMN_NAME: [91, 182], C.YIELD_COLUMN_NAME: [24.917, 25.358]}})
StateManager.set("df_data", df)
from ui.primary_yield_calculator import render_primary_yield_calculator
render_primary_yield_calculator()
"""
    at = AppTest.from_string(script, default_timeout=30).run()
    assert at.number_input(key="yield_rate_input").value == 25.0
    at.checkbox(key="use_latest").check().run()
    assert at.number_input(key="yield_rate_input").value == 24.917
    at.selectbox[0].select(182).run()
    assert at.number_input(key="yield_rate_input").value == 25.358


def test_postgres_alert_dedupe_and_retired_tenor(tmp_path, monkeypatch):
    """نفس المنطق على PostgreSQL حقيقي (يتخطى لو pgserver غير مثبت)."""
    import pytest

    pgserver = pytest.importorskip("pgserver")
    import tempfile

    srv = pgserver.get_server(tempfile.mkdtemp(prefix="pgalerts_"))
    try:
        uri = srv.get_uri().replace("postgresql://", "postgres://", 1)
        monkeypatch.setenv("POSTGRES_URI", uri)
        import streamlit as st
        import postgres_manager as m

        m.dispose_shared_engines()
        st.cache_data.clear()
        st.cache_resource.clear()
        db = m.PostgresDBManager()
        db.save_data(
            _rows(
                [
                    (91, 24.0, "01/11/2026"),
                    (91, 25.0, "08/11/2026"),
                    (int("3" + "36"), 23.2, "01/03/2026"),
                    (int("3" + "36"), 23.4, "08/03/2026"),
                ]
            )
        )
        alerts = db.check_yield_changes(0.5)
        assert [a["tenor"] for a in alerts] == [91]
        first = u.AlertManager(cache_file=tmp_path / "p1.json", engine=db.engine)
        assert not first.is_duplicate(alerts[0])
        first.mark_sent(alerts[0])
        first.mark_sent(alerts[0])  # مرتان: لا يجب أن يفشل (ON CONFLICT)
        second = u.AlertManager(cache_file=tmp_path / "p2.json", engine=db.engine)
        assert second.is_duplicate(alerts[0])
    finally:
        m.dispose_shared_engines()
        srv.cleanup()


def test_secondary_calculator_latest_yield_follows_tenor():
    from streamlit.testing.v1 import AppTest

    root = str(Path(__file__).resolve().parent.parent)
    script = f"""
import sys
sys.path.insert(0, {root!r})
import pandas as pd
import constants as C
from state_manager import StateManager
df = pd.DataFrame({{C.TENOR_COLUMN_NAME: [91, 273], C.YIELD_COLUMN_NAME: [24.917, 26.289]}})
StateManager.set("df_data", df)
from ui.secondary_sale_calculator import render_secondary_sale_calculator
render_secondary_sale_calculator()
"""
    at = AppTest.from_string(script, default_timeout=30).run()
    assert at.number_input(key="sec_orig_yield").value == 25.0
    at.checkbox(key="use_latest_original").check().run()
    at.selectbox(key="sec_tenor").select(273).run()
    assert at.number_input(key="sec_orig_yield").value == 26.289
    assert not at.exception
