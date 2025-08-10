# postgres_manager.py (النسخة النهائية مع إضافة الدالة المفقودة)
import logging
import os
import pandas as pd
import pytz
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy import create_engine, text
import streamlit as st
from dotenv import load_dotenv
from treasury_core.ports import HistoricalDataStore
import constants as C
from datetime import datetime, timedelta

load_dotenv()

logger = logging.getLogger(__name__)


class PostgresDBManager(HistoricalDataStore):
    def __init__(self):
        self.conn_uri = os.environ.get("POSTGRES_URI")
        if not self.conn_uri:
            raise ValueError("متغير البيئة POSTGRES_URI غير موجود.")

        sqlalchemy_uri = self.conn_uri.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )
        self.engine = create_engine(sqlalchemy_uri)
        self._init_db()

    def _get_connection(self):
        return self.engine.connect()

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                with conn.begin():
                    conn.execute(
                        text(
                            f"""
                            CREATE TABLE IF NOT EXISTS "{C.TABLE_NAME}" (
                                "{C.TENOR_COLUMN_NAME}" INTEGER NOT NULL,
                                "{C.YIELD_COLUMN_NAME}" REAL NOT NULL,
                                "{C.SESSION_DATE_COLUMN_NAME}" TEXT NOT NULL,
                                "{C.DATE_COLUMN_NAME}" TIMESTAMPTZ NOT NULL,
                                PRIMARY KEY ("{C.TENOR_COLUMN_NAME}", "{C.SESSION_DATE_COLUMN_NAME}")
                            );
                            """
                        )
                    )
            logger.info("✅ PostgreSQL table initialized or already exists.")
        except Exception as e:
            logger.error(
                f"❌ PostgreSQL initialization failed: {str(e)}", exc_info=True
            )
            raise

    def save_data(self, df: pd.DataFrame) -> None:
        if df.empty:
            logger.warning("⚠️ لا توجد بيانات للحفظ.")
            return

        df_to_save = df.copy()
        if "session_date_dt" in df_to_save.columns:
            df_to_save.drop(columns=["session_date_dt"], inplace=True)

        # التحقق من صحة التواريخ قبل الحفظ
        df_to_save[C.DATE_COLUMN_NAME] = pd.to_datetime(
            df_to_save[C.DATE_COLUMN_NAME], errors="coerce"
        )

        # التحقق من وجود تواريخ غير صالحة (1970-01-01)
        invalid_dates = df_to_save[C.DATE_COLUMN_NAME].dt.year == 1970
        if invalid_dates.any():
            logger.warning(
                f"⚠️ تم العثور على {invalid_dates.sum()} سجل بتاريخ غير صالح (1970)، سيتم إزالته"
            )
            df_to_save = df_to_save[~invalid_dates]

        df_to_save = df_to_save[df_to_save[C.DATE_COLUMN_NAME].notnull()]
        if df_to_save.empty:
            logger.warning("⚠️ لم يتم حفظ أي بيانات: جميع القيم الزمنية غير صالحة.")
            return

        if df_to_save[C.DATE_COLUMN_NAME].dt.tz is None:
            df_to_save[C.DATE_COLUMN_NAME] = df_to_save[
                C.DATE_COLUMN_NAME
            ].dt.tz_localize("UTC")
        else:
            df_to_save[C.DATE_COLUMN_NAME] = df_to_save[
                C.DATE_COLUMN_NAME
            ].dt.tz_convert("UTC")

        # DEBUG: طباعة عدد الصفوف وقيم الأعمدة الأساسية قبل الحفظ
        debug_cols = [
            C.TENOR_COLUMN_NAME,
            C.YIELD_COLUMN_NAME,
            C.SESSION_DATE_COLUMN_NAME,
        ]
        logger.info(f"[DEBUG] سيتم حفظ {len(df_to_save)} صف في PostgreSQL:")
        logger.info(f"[DEBUG] القيم:\n{df_to_save[debug_cols].to_string(index=False)}")

        session_dates = df_to_save[C.SESSION_DATE_COLUMN_NAME].unique().tolist()
        records = df_to_save.to_dict("records")

        try:
            with self._get_connection() as conn:
                with conn.begin():
                    # حذف الصفوف القديمة لكل session_date
                    conn.execute(
                        text(
                            f'DELETE FROM "{C.TABLE_NAME}" WHERE "{C.SESSION_DATE_COLUMN_NAME}" IN :session_dates'
                        ),
                        {"session_dates": tuple(session_dates)},
                    )
                    # حفظ الصفوف الجديدة
                    conn.execute(
                        text(
                            f"""
                            INSERT INTO "{C.TABLE_NAME}" 
                            ("{C.TENOR_COLUMN_NAME}", "{C.YIELD_COLUMN_NAME}", 
                             "{C.SESSION_DATE_COLUMN_NAME}", "{C.DATE_COLUMN_NAME}")
                            VALUES (:tenor, :yield, :session_date, :date)
                            """
                        ),
                        [
                            {
                                "tenor": row[C.TENOR_COLUMN_NAME],
                                "yield": row[C.YIELD_COLUMN_NAME],
                                "session_date": row[C.SESSION_DATE_COLUMN_NAME],
                                "date": row[C.DATE_COLUMN_NAME],
                            }
                            for row in records
                        ],
                    )
            logger.info(f"💾 {len(df_to_save)} سجل تم حفظه في PostgreSQL.")
        except Exception as e:
            logger.error(
                f"❌ فشل في حفظ البيانات إلى PostgreSQL: {str(e)}", exc_info=True
            )
            raise

    def clear_all_data(self) -> None:
        try:
            with self._get_connection() as conn:
                with conn.begin():
                    conn.execute(
                        text(f'TRUNCATE TABLE "{C.TABLE_NAME}" RESTART IDENTITY;')
                    )
            logger.info(f"🗑️ تم مسح جميع البيانات من الجدول: {C.TABLE_NAME}")
        except Exception as e:
            logger.error(
                f"❌ فشل في مسح البيانات من PostgreSQL: {str(e)}", exc_info=True
            )
            raise

    def load_latest_data(
        self,
    ) -> Tuple[pd.DataFrame, Tuple[Optional[str], Optional[str]]]:
        try:
            with self._get_connection() as conn:
                query = text(
                    f"""
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
                """
                )
                df = pd.read_sql_query(query, conn)

                if df.empty or "max_scrape_date" not in df.columns:
                    return pd.DataFrame(), ("البيانات الأولية", None)

                max_scrape_date = df["max_scrape_date"].iloc[0]

                # التحقق من أن التاريخ ليس None أو NaT
                if pd.isnull(max_scrape_date):
                    logger.warning("⚠️ تاريخ الاستخراج غير صالح (None/NaT)")
                    return pd.DataFrame(), ("البيانات الأولية", None)

                last_update_dt_utc = pd.to_datetime(max_scrape_date, errors="coerce")
                if pd.isnull(last_update_dt_utc):
                    logger.warning("⚠️ فشل تحويل تاريخ الاستخراج")
                    return pd.DataFrame(), ("البيانات الأولية", None)

                # التحقق من أن التاريخ ليس 1970-01-01 (Unix epoch)
                if last_update_dt_utc.year == 1970:
                    logger.warning("⚠️ تاريخ الاستخراج غير صالح (1970-01-01)")
                    return pd.DataFrame(), ("البيانات الأولية", None)

                if last_update_dt_utc.tzinfo is None:
                    last_update_dt_utc = last_update_dt_utc.tz_localize("UTC")
                else:
                    last_update_dt_utc = last_update_dt_utc.tz_convert("UTC")

                cairo_tz = pytz.timezone(C.TIMEZONE)
                last_update_dt_cairo = last_update_dt_utc.astimezone(cairo_tz)

                last_update_date = last_update_dt_cairo.strftime("%Y-%m-%d")
                last_update_time = last_update_dt_cairo.strftime("%I:%M %p")

                df.drop(columns=["max_scrape_date"], inplace=True)
                return df, (last_update_date, last_update_time)

        except Exception as e:
            logger.warning(
                f"⚠️ لم يتم تحميل البيانات الأخيرة من PostgreSQL: {str(e)}",
                exc_info=True,
            )
            return pd.DataFrame(), ("البيانات الأولية", None)

    @st.cache_data
    def load_all_historical_data(_self) -> pd.DataFrame:
        try:
            with _self.engine.connect() as conn:
                query = text(f'SELECT * FROM "{C.TABLE_NAME}"')
                df = pd.read_sql_query(query, conn)

                if df.empty:
                    return pd.DataFrame()

                df[C.DATE_COLUMN_NAME] = pd.to_datetime(df[C.DATE_COLUMN_NAME])
                return df.sort_values(by=C.DATE_COLUMN_NAME, ascending=False)

        except Exception as e:
            logger.error(
                f"❌ فشل تحميل البيانات التاريخية من PostgreSQL: {str(e)}",
                exc_info=True,
            )
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
            with self._get_connection() as conn:
                with conn.begin():
                    query = text(
                        f"""
                        SELECT "{C.SESSION_DATE_COLUMN_NAME}"
                        FROM "{C.TABLE_NAME}"
                        ORDER BY to_date("{C.SESSION_DATE_COLUMN_NAME}", 'DD/MM/YYYY') DESC
                        LIMIT 1;
                        """
                    )
                    result = conn.execute(query).fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(
                f"❌ فشل في جلب آخر تاريخ جلسة من PostgreSQL: {str(e)}", exc_info=True
            )
            return None

    def get_data_hash_for_date(self, session_date: str) -> Optional[str]:
        try:
            with self._get_connection() as conn:
                query = text(
                    f"""
                    SELECT 
                        MD5(string_agg(
                            {C.TENOR_COLUMN_NAME}::text || {C.YIELD_COLUMN_NAME}::text, 
                            '' ORDER BY {C.TENOR_COLUMN_NAME}
                        )) as data_hash
                    FROM "{C.TABLE_NAME}"
                    WHERE "{C.SESSION_DATE_COLUMN_NAME}" = :session_date
                """
                )
                result = conn.execute(query, {"session_date": session_date}).fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"فشل في حساب تجزئة البيانات: {str(e)}", exc_info=True)
            return None

    def detect_data_gaps(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                query = text(
                    f"""
                    SELECT "{C.SESSION_DATE_COLUMN_NAME}"
                    FROM "{C.TABLE_NAME}"
                    GROUP BY "{C.SESSION_DATE_COLUMN_NAME}"
                    ORDER BY to_date("{C.SESSION_DATE_COLUMN_NAME}", 'DD/MM/YYYY')
                """
                )
                db_dates = [row[0] for row in conn.execute(query).fetchall()]

            if not db_dates:
                return []

            date_format = "%d/%m/%Y"
            db_date_objects = sorted(
                [datetime.strptime(d, date_format) for d in db_dates]
            )

            gaps = []
            for i in range(1, len(db_date_objects)):
                diff = (db_date_objects[i] - db_date_objects[i - 1]).days
                if diff > 1:
                    current = db_date_objects[i - 1] + timedelta(days=1)
                    gap_days = []

                    while current < db_date_objects[i]:
                        if current.weekday() not in [4, 5]:  # Friday, Saturday
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
        if new_data.empty:
            return False, "البيانات فارغة"

        session_dates = new_data[C.SESSION_DATE_COLUMN_NAME].unique().tolist()

        try:
            with self._get_connection() as conn:
                # جلب كل الصفوف من قاعدة البيانات حيث session_date IN (...)
                placeholders = ",".join(
                    [f":session_date_{i}" for i in range(len(session_dates))]
                )
                select_sql = f'SELECT * FROM "{C.TABLE_NAME}" WHERE "{C.SESSION_DATE_COLUMN_NAME}" IN ({placeholders})'
                select_params = {
                    f"session_date_{i}": v for i, v in enumerate(session_dates)
                }
                current_data = pd.read_sql_query(
                    text(select_sql), conn, params=select_params
                )

                if current_data.empty:
                    return False, "لا توجد بيانات سابقة لهذه التواريخ"

                # قارن فقط الأعمدة الأساسية
                cols_to_compare = [
                    C.TENOR_COLUMN_NAME,
                    C.YIELD_COLUMN_NAME,
                    C.SESSION_DATE_COLUMN_NAME,
                ]
                current_data = current_data.sort_values(by=cols_to_compare).reset_index(
                    drop=True
                )
                new_data_sorted = new_data.sort_values(by=cols_to_compare).reset_index(
                    drop=True
                )

                if len(current_data) != len(new_data_sorted):
                    return (
                        False,
                        f"عدد الصفوف مختلف ({len(current_data)} مقابل {len(new_data_sorted)})",
                    )

                try:
                    pd.testing.assert_frame_equal(
                        current_data[cols_to_compare],
                        new_data_sorted[cols_to_compare],
                        check_dtype=False,
                        atol=0.001,
                    )
                    return True, "البيانات متطابقة تمامًا."
                except AssertionError as e:
                    return False, f"البيانات مختلفة: {str(e)}"

        except Exception as e:
            logger.error(f"فشل في تحليل البيانات المكررة: {str(e)}", exc_info=True)
            return False, f"خطأ في التحليل: {str(e)}"

    def get_daily_update_count(self) -> int:
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            with self._get_connection() as conn:
                query = text(
                    f"""
                    SELECT COUNT(DISTINCT "{C.SESSION_DATE_COLUMN_NAME}") 
                    FROM "{C.TABLE_NAME}"
                    WHERE DATE("{C.DATE_COLUMN_NAME}" AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Cairo') = :today
                """
                )
                result = conn.execute(query, {"today": today_str}).fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"فشل في حساب عدد التحديثات اليومية: {str(e)}", exc_info=True)
            return 0

    def vacuum_database(self):
        """تحسين هيكل قاعدة البيانات وتحرير المساحة في PostgreSQL"""
        try:
            # Use a connection with autocommit to run VACUUM outside a transaction block
            with self.engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as conn:
                conn.execute(text("VACUUM ANALYZE"))
            logger.info("✅ تم تنفيذ VACUUM وANALYZE بنجاح على PostgreSQL")
        except Exception as e:
            logger.error(f"فشل في تنفيذ VACUUM على PostgreSQL: {str(e)}", exc_info=True)

    def clean_old_records(self, cutoff_date_str: str) -> int:
        """
        مسح السجلات الأقدم من تاريخ محدد في PostgreSQL.
        Args:
            cutoff_date_str: التاريخ المحدد (بتنسيق 'YYYY-MM-DD').
        Returns:
            عدد السجلات التي تم حذفها.
        """
        try:
            with self._get_connection() as conn:
                with conn.begin():
                    # Use standard SQL CAST for better compatibility
                    query = text(
                        f'DELETE FROM "{C.TABLE_NAME}" WHERE "{C.DATE_COLUMN_NAME}" < CAST(:cutoff_date AS DATE)'
                    )
                    result = conn.execute(query, {"cutoff_date": cutoff_date_str})
                    deleted_rows = result.rowcount
                    logger.info(
                        f"🗑️ تم حذف {deleted_rows} سجل من PostgreSQL أقدم من {cutoff_date_str}."
                    )
                    return deleted_rows
        except Exception as e:
            logger.error(
                f"❌ فشل في حذف السجلات القديمة من PostgreSQL: {str(e)}", exc_info=True
            )
            raise


@st.cache_resource
def get_db_manager() -> HistoricalDataStore:
    return PostgresDBManager()
