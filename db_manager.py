# db_manager.py
import pandas as pd
import os
import logging
from typing import Tuple, Optional, List, Dict, Any
import streamlit as st
import pytz
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path  # ✅ تم إضافة هذا الاستيراد

from treasury_core.ports import HistoricalDataStore
import constants as C

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ✅ تم التعديل هنا: استخدام مسار مطلق بناءً على موقع الملف
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


class SQLiteDBManager(HistoricalDataStore):
    def __init__(self, db_filename: str = C.DB_FILENAME):
        # ✅ تم التعديل هنا: ربط المسار المطلق للمجلد مع اسم الملف
        self.db_filename = db_filename
        self.db_path = DATA_DIR / db_filename
        db_uri = f"sqlite:///{self.db_path}"

        # تكوين مُحسّن لـ SQLite
        connect_args = {
            "check_same_thread": False,
            "timeout": 30,  # زيادة المهلة الزمنية
        }

        # إعدادات أداء مُحسّنة
        engine_args = {
            "pool_size": 10,
            "pool_recycle": 3600,
            "connect_args": connect_args,
            "echo": False,  # تعطيل التسجيل للإنتاج
        }

        # تكوين PRAGMA لتحسين الأداء
        def set_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
            cursor.close()

        from sqlalchemy import event

        self.engine = create_engine(db_uri, **engine_args)
        event.listen(self.engine, "connect", set_pragma)

        self._init_db()

    def _init_db(self) -> None:
        try:
            # ✅ تم التعديل: استخدام المحرك للاتصال وتنفيذ الأوامر
            with self.engine.connect() as conn:
                # إنشاء الجدول
                conn.execute(
                    text(
                        f"""
                    CREATE TABLE IF NOT EXISTS "{C.TABLE_NAME}" (
                        "{C.TENOR_COLUMN_NAME}" INTEGER NOT NULL,
                        "{C.YIELD_COLUMN_NAME}" REAL NOT NULL,
                        "{C.SESSION_DATE_COLUMN_NAME}" TEXT NOT NULL,
                        "{C.DATE_COLUMN_NAME}" DATETIME NOT NULL,
                        PRIMARY KEY ("{C.TENOR_COLUMN_NAME}", "{C.SESSION_DATE_COLUMN_NAME}")
                    )
                """
                    )
                )

                # فهارس مُحسّنة لمشروع كبير
                conn.execute(
                    text(
                        f"""
                    CREATE INDEX IF NOT EXISTS idx_session_date ON "{C.TABLE_NAME}" (
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 7, 4),
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 4, 2),
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 1, 2)
                    )
                """
                    )
                )

                conn.execute(
                    text(
                        f"""
                    CREATE INDEX IF NOT EXISTS idx_date ON "{C.TABLE_NAME}" ("{C.DATE_COLUMN_NAME}")
                """
                    )
                )

                conn.execute(
                    text(
                        f"""
                    CREATE INDEX IF NOT EXISTS idx_tenor ON "{C.TABLE_NAME}" ("{C.TENOR_COLUMN_NAME}")
                """
                    )
                )

                conn.commit()
                logger.info("✅ Database and indexes initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}", exc_info=True)
            raise

    def save_data(self, df: pd.DataFrame) -> None:
        if df.empty:
            logger.warning("⚠️ لا توجد بيانات للحفظ.")
            return

        df_to_save = df.copy()
        if "session_date_dt" in df_to_save.columns:
            df_to_save.drop(columns=["session_date_dt"], inplace=True)

        # تحويل التاريخ إلى string لـ SQLite
        if C.DATE_COLUMN_NAME in df_to_save.columns:
            df_to_save[C.DATE_COLUMN_NAME] = df_to_save[C.DATE_COLUMN_NAME].astype(str)

        try:
            # تحسين الكتابة باستخدام executemany
            with self.engine.begin() as conn:
                # تحويل DataFrame إلى قائمة سجلات
                records = df_to_save.to_dict("records")

                # استخدام executemany مع قائمة من القواميس
                conn.execute(
                    text(
                        f"""
                        INSERT OR REPLACE INTO "{C.TABLE_NAME}" 
                        ("{C.TENOR_COLUMN_NAME}", "{C.YIELD_COLUMN_NAME}", 
                         "{C.SESSION_DATE_COLUMN_NAME}", "{C.DATE_COLUMN_NAME}")
                        VALUES (:tenor, :yield, :session_date, :scrape_date)
                    """
                    ),
                    records,
                )

            logger.info(f"💾 {len(df_to_save)} سجل تم حفظه في SQLite.")
        except Exception as e:
            logger.error(f"Failed to save data to database: {e}", exc_info=True)

    def load_latest_data(
        self,
    ) -> Tuple[pd.DataFrame, Tuple[Optional[str], Optional[str]]]:
        try:
            # استخدام استعلام مُحسّن بدون CTE
            query = f"""
                SELECT 
                    t."{C.TENOR_COLUMN_NAME}", 
                    t."{C.YIELD_COLUMN_NAME}", 
                    t."{C.SESSION_DATE_COLUMN_NAME}",
                    (SELECT MAX("{C.DATE_COLUMN_NAME}") FROM "{C.TABLE_NAME}") as max_scrape_date
                FROM "{C.TABLE_NAME}" t
                WHERE t."{C.DATE_COLUMN_NAME}" = (
                    SELECT MAX(t2."{C.DATE_COLUMN_NAME}") 
                    FROM "{C.TABLE_NAME}" t2 
                    WHERE t2."{C.TENOR_COLUMN_NAME}" = t."{C.TENOR_COLUMN_NAME}"
                )
                LIMIT {len(C.TENORS)}  -- لأننا نعرف عدد الآجال مسبقاً
            """
            df = pd.read_sql_query(query, self.engine)

            if not df.empty:
                # معالجة أسرع لتحويل التوقيت
                last_update_dt_utc = pd.to_datetime(df["max_scrape_date"].iloc[0])
                cairo_tz = pytz.timezone(C.TIMEZONE)

                # تجنب التحويلات الزائدة إذا كانت البيانات بالفعل بتوقيت UTC
                if last_update_dt_utc.tzinfo is None:
                    last_update_dt_utc = last_update_dt_utc.tz_localize("UTC")

                last_update_dt_cairo = last_update_dt_utc.astimezone(cairo_tz)
                last_update_date = last_update_dt_cairo.strftime("%Y-%m-%d")
                last_update_time = last_update_dt_cairo.strftime("%I:%M %p")

                df = df.drop(columns=["max_scrape_date"])
                return df, (last_update_date, last_update_time)

            return pd.DataFrame(), ("البيانات الأولية", None)
        except Exception as e:
            logger.warning(
                f"Could not load latest data (table might be empty): {e}", exc_info=True
            )
            return pd.DataFrame(), ("البيانات الأولية", None)

    def load_all_historical_data(self) -> pd.DataFrame:
        try:
            # استخدام استعلام مُقسّم لتجنب استهلاك الذاكرة
            chunk_size = 5000  # حجم الكتلة المناسب
            all_dfs = []
            offset = 0

            while True:
                query = text(
                    f"""
                    SELECT * FROM "{C.TABLE_NAME}"
                    ORDER BY "{C.DATE_COLUMN_NAME}" DESC
                    LIMIT {chunk_size} OFFSET {offset}
                """
                )

                chunk_df = pd.read_sql_query(query, self.engine)

                if chunk_df.empty:
                    break

                all_dfs.append(chunk_df)
                offset += chunk_size

                # التحقق من استخدام الذاكرة
                if sys.getsizeof(all_dfs) > 100 * 1024 * 1024:  # 100MB
                    logger.warning("⚠️ استخدام الذاكرة مرتفع، معالجة البيانات على مراحل")
                    return pd.concat(all_dfs)

            if all_dfs:
                return pd.concat(all_dfs)
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Failed to load historical  {e}", exc_info=True)
            return pd.DataFrame()

    def check_yield_changes(self, threshold_percent: float = 0.5) -> list:
        """
        تقوم بفحص التغييرات في العائد وإرجاع قائمة بالتنبيهات.
        """
        try:
            latest_data, _ = self.load_latest_data()
            if latest_data.empty:
                return []

            all_data = self.load_all_historical_data()
            if all_data.empty or len(all_data) < 2:
                return []

            # استخدام أسماء الأعمدة من ملف الثوابت
            date_col_name = C.SESSION_DATE_COLUMN_NAME
            tenor_col = C.TENOR_COLUMN_NAME
            yield_col = C.YIELD_COLUMN_NAME

            latest_data[date_col_name] = pd.to_datetime(
                latest_data[date_col_name], dayfirst=True, errors="coerce"
            )
            all_data[date_col_name] = pd.to_datetime(
                all_data[date_col_name], dayfirst=True, errors="coerce"
            )

            latest_data.dropna(subset=[date_col_name], inplace=True)
            all_data.dropna(subset=[date_col_name], inplace=True)

            if latest_data.empty or all_data.empty:
                return []

            latest_date = latest_data[date_col_name].max()

            # استبعاد التواريخ المساوية أو الأحدث من التاريخ الأخير
            previous_data_full = all_data[
                all_data[date_col_name].dt.date < latest_date.date()
            ]

            if previous_data_full.empty:
                return []

            previous_date = previous_data_full[date_col_name].max()
            previous_data = previous_data_full[
                previous_data_full[date_col_name] == previous_date
            ]

            merged_data = pd.merge(
                latest_data, previous_data, on=tenor_col, suffixes=("_latest", "_prev")
            )

            if merged_data.empty:
                return []

            merged_data["change_percent"] = (
                (merged_data[f"{yield_col}_latest"] - merged_data[f"{yield_col}_prev"])
                / merged_data[f"{yield_col}_prev"]
            ) * 100

            alerts_df = merged_data[
                abs(merged_data["change_percent"]) >= threshold_percent
            ]

            alerts = []
            for _, row in alerts_df.iterrows():
                alerts.append(
                    {
                        "tenor": row[tenor_col],
                        "latest_yield": row[f"{yield_col}_latest"],
                        "previous_yield": row[f"{yield_col}_prev"],
                        "change_percent": row["change_percent"],
                        "direction": "زيادة" if row["change_percent"] > 0 else "انخفاض",
                        "latest_date": latest_date.strftime("%Y-%m-%d"),
                        "previous_date": previous_date.strftime("%Y-%m-%d"),
                    }
                )

            return alerts
        except Exception as e:
            logger.error(f"ERROR in check_yield_changes: {e}", exc_info=True)
            return []

    def get_latest_session_date(self) -> Optional[str]:
        try:
            # استخدام استعلام أكثر كفاءة
            with self.engine.connect() as conn:
                query = text(
                    f"""
                    SELECT "{C.SESSION_DATE_COLUMN_NAME}"
                    FROM "{C.TABLE_NAME}"
                    ORDER BY 
                        strftime('%Y-%m-%d', 
                            SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 7, 4) || '-' ||
                            SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 4, 2) || '-' ||
                            SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 1, 2)
                        ) DESC
                    LIMIT 1;
                    """
                )
                result = conn.execute(query).fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Failed to get latest session date: {e}", exc_info=True)
            return None

    def get_data_hash_for_date(self, session_date: str) -> Optional[str]:
        """
        استرجاع تجزئة البيانات لجلسة معينة.
        Args:
            session_date: تاريخ الجلسة لاسترجاع تجزئة البيانات له
        Returns:
            تجزئة MD5 للبيانات أو None في حالة الفشل
        """
        try:
            with self.engine.connect() as conn:
                # استخدام دالة GROUP_CONCAT لـ SQLite
                query = text(
                    f"""
                    SELECT 
                        HEX(MD5(GROUP_CONCAT(
                            {C.TENOR_COLUMN_NAME} || {C.YIELD_COLUMN_NAME}, 
                            '' ORDER BY {C.TENOR_COLUMN_NAME}
                        ))) as data_hash
                    FROM {C.TABLE_NAME}
                    WHERE {C.SESSION_DATE_COLUMN_NAME} = :session_date
                    """
                )
                result = conn.execute(query, {"session_date": session_date}).fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"فشل في حساب تجزئة البيانات: {str(e)}", exc_info=True)
            return None

    def detect_data_gaps(self) -> List[Dict[str, Any]]:
        """
        الكشف عن الفجوات في البيانات التاريخية بدقة.
        Returns:
            قائمة تحتوي على تفاصيل الفجوات المكتشفة
        """
        try:
            # الحصول على جميع تواريخ الجلسات من قاعدة البيانات
            with self.engine.connect() as conn:
                query = text(
                    f"""
                    SELECT DISTINCT "{C.SESSION_DATE_COLUMN_NAME}" 
                    FROM "{C.TABLE_NAME}"
                    ORDER BY 
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 7, 4) DESC,
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 4, 2) DESC,
                        SUBSTR("{C.SESSION_DATE_COLUMN_NAME}", 1, 2) DESC
                    """
                )
                db_dates = [row[0] for row in conn.execute(query).fetchall()]

            if not db_dates:
                return []

            # تحويل التواريخ إلى كائنات datetime للفحص
            date_format = "%d/%m/%Y"

            # تحويل التواريخ إلى قائمة كائنات datetime
            db_date_objects = [datetime.strptime(d, date_format) for d in db_dates]

            # فرز التواريخ
            db_date_objects.sort()

            # الكشف عن الفجوات
            gaps = []
            for i in range(1, len(db_date_objects)):
                diff = (db_date_objects[i] - db_date_objects[i - 1]).days
                if diff > 1:  # فجوة تزيد عن يوم واحد
                    # تجاهل العطلات الأسبوعية (الجمعة والسبت)
                    current = db_date_objects[i - 1] + timedelta(days=1)
                    gap_days = []

                    while current < db_date_objects[i]:
                        # تجاهل العطلات
                        if current.weekday() not in [4, 5]:  # الجمعة والسبت
                            gap_days.append(current)
                        current += timedelta(days=1)

                    if gap_days:
                        gaps.append(
                            {
                                "start_date": db_date_objects[i - 1].strftime(
                                    date_format
                                ),
                                "end_date": db_date_objects[i].strftime(date_format),
                                "missing_dates": [
                                    d.strftime(date_format) for d in gap_days
                                ],
                                "gap_length": len(gap_days),
                            }
                        )

            return gaps
        except Exception as e:
            logger.error(f"فشل في كشف الفجوات: {str(e)}", exc_info=True)
            return []

    def is_duplicate_data(self, new_data: pd.DataFrame) -> Tuple[bool, str]:
        """
        تحليل دقيق لتحديد ما إذا كانت البيانات الجديدة مكررة.

        Args:
            new_data: البيانات الجديدة المراد مقارنتها

        Returns:
            (is_duplicate, reason) - هل البيانات مكررة ولماذا
        """
        if new_data.empty:
            return False, "البيانات فارغة"

        # الحصول على أحدث تاريخ جلسة
        latest_session_date = new_data[C.SESSION_DATE_COLUMN_NAME].iloc[0]

        # جلب البيانات الحالية لهذا التاريخ
        try:
            with self.engine.connect() as conn:
                query = text(
                    f"""
                    SELECT * FROM "{C.TABLE_NAME}"
                    WHERE "{C.SESSION_DATE_COLUMN_NAME}" = :session_date
                    """
                )
                current_data = pd.read_sql_query(
                    query, conn, params={"session_date": latest_session_date}
                )

                if current_data.empty:
                    return False, "لا توجد بيانات سابقة لهذا التاريخ"

                # مقارنة البيانات بشكل دقيق
                # فرز البيانات حسب الآجال للتأكد من المقارنة الصحيحة
                current_data = current_data.sort_values(by=C.TENOR_COLUMN_NAME)
                new_data_sorted = new_data.sort_values(by=C.TENOR_COLUMN_NAME)

                # التحقق من عدد الآجال
                if len(current_data) != len(new_data_sorted):
                    return (
                        False,
                        f"عدد الآجال مختلف ({len(current_data)} مقابل {len(new_data_sorted)})",
                    )

                # التحقق من الاختلافات في القيم
                tolerance = 0.001  # 0.1% هامش خطأ مقبول

                # تحويل البيانات إلى مصفوفات لمقارنة أسرع
                current_yields = current_data[C.YIELD_COLUMN_NAME].values
                new_yields = new_data_sorted[C.YIELD_COLUMN_NAME].values

                # التحقق من الاختلافات في القيم
                differences = abs(current_yields - new_yields)
                max_diff = differences.max()

                if max_diff <= tolerance:
                    return True, f"البيانات متطابقة مع هامش خطأ {max_diff:.6f}"
                else:
                    # تحديد الآجال التي تختلف
                    different_tenors = []
                    for i, diff in enumerate(differences):
                        if diff > tolerance:
                            tenor = current_data[C.TENOR_COLUMN_NAME].iloc[i]
                            old_yield = current_yields[i]
                            new_yield = new_yields[i]
                            different_tenors.append(
                                f"{tenor} يوم: {old_yield:.4f}% → {new_yield:.4f}% (فرق: {diff:.4f}%)"
                            )

                    return (
                        False,
                        f"اختلاف في {len(different_tenors)} آجال: {', '.join(different_tenors[:3])}"
                        + ("..." if len(different_tenors) > 3 else ""),
                    )

        except Exception as e:
            logger.error(f"فشل في تحليل البيانات المكررة: {str(e)}", exc_info=True)
            return False, f"خطأ في التحليل: {str(e)}"

    def get_daily_update_count(self) -> int:
        """
        حساب عدد مرات التحديث في اليوم الحالي.
        Returns:
            عدد مرات التحديث في اليوم الحالي
        """
        try:
            # تحويل التاريخ إلى تنسيق DD/MM/YYYY للاستخدام في الاستعلام
            today_ddmmyyyy = datetime.now().strftime("%d/%m/%Y")

            with self.engine.connect() as conn:
                query = text(
                    f"""
                    SELECT COUNT(DISTINCT "{C.SESSION_DATE_COLUMN_NAME}") 
                    FROM "{C.TABLE_NAME}"
                    WHERE "{C.SESSION_DATE_COLUMN_NAME}" = :today_ddmmyyyy
                    """
                )
                result = conn.execute(
                    query, {"today_ddmmyyyy": today_ddmmyyyy}
                ).fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"فشل في حساب عدد التحديثات اليومية: {str(e)}", exc_info=True)
            return 0

    def clean_old_records(self, cutoff_date_str: str) -> int:
        """
        مسح السجلات الأقدم من تاريخ محدد.
        Args:
            cutoff_date_str: التاريخ المحدد (بتنسيق 'YYYY-MM-DD').
        Returns:
            عدد السجلات التي تم حذفها.
        """
        try:
            with self.engine.begin() as conn:
                query = text(
                    f'DELETE FROM "{C.TABLE_NAME}" WHERE "{C.DATE_COLUMN_NAME}" < :cutoff_date'
                )
                result = conn.execute(query, {"cutoff_date": cutoff_date_str})
                deleted_rows = result.rowcount
                logger.info(f"🗑️ تم حذف {deleted_rows} سجل أقدم من {cutoff_date_str}.")
                return deleted_rows
        except Exception as e:
            logger.error(f"❌ فشل في حذف السجلات القديمة: {str(e)}", exc_info=True)
            raise

    def vacuum_database(self):
        """تحسين هيكل قاعدة البيانات وتحرير المساحة"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("VACUUM"))
                conn.execute(text("ANALYZE"))
            logger.info("✅ تم تنفيذ VACUUM وANALYZE بنجاح")
        except Exception as e:
            logger.error(f"فشل في تنفيذ VACUUM: {str(e)}", exc_info=True)

    def clear_all_data(self) -> None:
        """مسح جميع البيانات من الجدول الرئيسي في SQLite"""
        try:
            with self.engine.begin() as conn:
                conn.execute(text(f'DELETE FROM "{C.TABLE_NAME}"'))
            logger.info(f"🗑️ تم مسح جميع البيانات من الجدول: {C.TABLE_NAME}")
        except Exception as e:
            logger.error(f"❌ فشل في مسح البيانات من SQLite: {str(e)}", exc_info=True)
            raise

    def _run_query_in_background(self, query: str, params: dict = None) -> pd.DataFrame:
        """تشغيل الاستعلام في خيط منفصل لتجنب حظر البرنامج الرئيسي"""

        def query_worker():
            try:
                with self.engine.connect() as conn:
                    return pd.read_sql_query(text(query), conn, params=params)
            except Exception as e:
                logger.error(f"فشل في تنفيذ الاستعلام في الخلفية: {e}", exc_info=True)
                return pd.DataFrame()

        # تشغيل الاستعلام في خيط منفصل
        with ThreadPoolExecutor() as executor:
            future = executor.submit(query_worker)
            try:
                return future.result(timeout=30)  # مهلة زمنية 30 ثانية
            except TimeoutError:
                logger.error("⏰ تجاوز الوقت المسموح للاستعلام")
                return pd.DataFrame()


@st.cache_resource
def get_db_manager(db_filename: str = C.DB_FILENAME) -> HistoricalDataStore:
    return SQLiteDBManager(db_filename)
