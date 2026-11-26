# tests/test_db_manager.py
import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db_manager import SQLiteDBManager
import constants as C


# =====================
# 🔧 Fixtures
# =====================
@pytest.fixture
def db(tmp_path) -> SQLiteDBManager:
    """🔧 يُعيد كائن قاعدة بيانات مؤقتة لاختبارات معزولة."""
    temp_db_file = tmp_path / "test.db"
    return SQLiteDBManager(db_filename=temp_db_file)


# =====================
# 🧪 Tests
# =====================


def test_initial_state_is_empty(db: SQLiteDBManager):
    """🧪 قاعدة البيانات في البداية فارغة ولا تحتوي على بيانات."""
    assert db.get_latest_session_date() is None

    df, msg = db.load_latest_data()
    assert "البيانات الأولية" in msg
    assert df.empty

    all_data = db.load_all_historical_data()
    assert all_data.empty


def test_save_and_load_multiple_sessions(db: SQLiteDBManager):
    """🧪 اختبار حفظ جلستين وتحميلهما بشكل صحيح."""

    # جلسة 1
    df1 = pd.DataFrame(
        {
            C.DATE_COLUMN_NAME: [pd.to_datetime("2025-01-05")],
            C.TENOR_COLUMN_NAME: [91],
            C.YIELD_COLUMN_NAME: [25.0],
            C.SESSION_DATE_COLUMN_NAME: ["05/01/2025"],
        }
    )
    db.save_data(df1)

    assert db.get_latest_session_date() == "05/01/2025"

    latest_df, _ = db.load_latest_data()
    assert len(latest_df) == 1
    assert latest_df.iloc[0][C.YIELD_COLUMN_NAME] == 25.0

    # جلسة 2
    df2 = pd.DataFrame(
        {
            C.DATE_COLUMN_NAME: [pd.to_datetime("2025-01-12")],
            C.TENOR_COLUMN_NAME: [357],
            C.YIELD_COLUMN_NAME: [27.0],
            C.SESSION_DATE_COLUMN_NAME: ["12/01/2025"],
        }
    )
    db.save_data(df2)

    all_data = db.load_all_historical_data()
    assert len(all_data) == 2

    latest_df2, _ = db.load_latest_data()
    assert len(latest_df2) == 2
    assert db.get_latest_session_date() == "12/01/2025"

    # تحقق من ترتيب الأعمدة حسب الآجل
    latest_sorted = latest_df2.sort_values(by=C.TENOR_COLUMN_NAME).reset_index(
        drop=True
    )
    assert latest_sorted[C.SESSION_DATE_COLUMN_NAME].tolist() == [
        "05/01/2025",
        "12/01/2025",
    ]
    assert latest_sorted[C.YIELD_COLUMN_NAME].tolist() == [25.0, 27.0]
