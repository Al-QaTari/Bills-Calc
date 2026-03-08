import streamlit as st
import time
import os
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
import hashlib
import json
import sys
import subprocess
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import constants as C

# تهيئة logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Constants
ALERT_CACHE_FILE = "sent_alerts_cache.json"
CACHE_DURATION = 24  # ساعة
PANEL_TIMEOUT = 300  # 5 دقائق
MAX_LOGIN_ATTEMPTS = 3


class AlertManager:
    def __init__(self):
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        """تحميل كاش التنبيهات مع إنشاء ملف جديد إذا لم يكن موجود"""
        try:
            if not os.path.exists(ALERT_CACHE_FILE):
                self._save_cache(
                    {"alerts": {}, "last_cleanup": datetime.now().isoformat()}
                )
                logger.info("تم إنشاء ملف كاش تنبيهات جديد")

            with open(ALERT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"فشل تحميل الذاكرة المؤقتة: {e}")
            return {"alerts": {}, "last_cleanup": datetime.now().isoformat()}

    def _save_cache(self, cache: dict) -> bool:
        """حفظ الكاش مع معالجة الأخطاء"""
        try:
            cache["last_cleanup"] = datetime.now().isoformat()
            with open(ALERT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            logger.error(f"فشل حفظ الذاكرة المؤقتة: {e}")
            return False

    def _generate_hash(self, alert: dict) -> str:
        """توليد هاش فريد للتنبيه"""
        key = f"{alert['tenor']}_{alert['latest_date']}_{alert['previous_date']}_{alert['change_percent']:.2f}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def is_duplicate(self, alert: dict) -> bool:
        """التحقق إذا التنبيه تم إرساله من قبل"""
        self.cache = self._cleanup_old_entries()
        return self._generate_hash(alert) in self.cache.get("alerts", {})

    def mark_sent(self, alert: dict) -> bool:
        """تسجيل التنبيه كمرسل"""
        alert_hash = self._generate_hash(alert)
        self.cache["alerts"][alert_hash] = {
            "timestamp": datetime.now().isoformat(),
            "tenor": alert["tenor"],
            "latest_date": alert["latest_date"],
            "change_percent": alert["change_percent"],
        }
        return self._save_cache(self.cache)

    def _cleanup_old_entries(self) -> dict:
        """حذف التنبيهات القديمة من الكاش"""
        cutoff_time = datetime.now() - timedelta(hours=CACHE_DURATION)
        cleaned_cache = {"alerts": {}}

        for alert_hash, alert_data in self.cache.get("alerts", {}).items():
            try:
                alert_time = datetime.fromisoformat(alert_data["timestamp"])
                if alert_time > cutoff_time:
                    cleaned_cache["alerts"][alert_hash] = alert_data
            except (ValueError, KeyError):
                continue

        return cleaned_cache

    def clear_cache(self) -> bool:
        """مسح الذاكرة المؤقتة"""
        try:
            if os.path.exists(ALERT_CACHE_FILE):
                os.remove(ALERT_CACHE_FILE)
                logger.info("تم مسح الذاكرة المؤقتة بنجاح")
                return True
            return False
        except Exception as e:
            logger.error(f"فشل مسح الذاكرة المؤقتة: {e}")
            return False

    def get_stats(self) -> dict:
        """إحصائيات الذاكرة المؤقتة"""
        return {
            "total_alerts": len(self.cache.get("alerts", {})),
            "last_cleanup": self.cache.get("last_cleanup", "غير متوفر"),
            "cache_file_exists": os.path.exists(ALERT_CACHE_FILE),
        }


# ==============================================================================
# vvvvvvvvvvvvvvvvvvvvvvvv  بداية الجزء الذي تم تعديله  vvvvvvvvvvvvvvvvvvvvvvvvvv
# ==============================================================================


class DatabaseManager:
    def __init__(self, data_store):
        self.data_store = data_store

    def get_latest_data(self):
        return self.data_store.load_latest_data()[0]

    def get_all_data(self):
        return self.data_store.load_all_historical_data()

    def check_yield_changes(self, threshold: float = 0.5) -> list:
        """
        النسخة النهائية والمصححة:
        تقوم بفحص التغيرات في العائد لكل أجل على حدة (شاملة جميع الآجال)،
        وتضمن أن جميع أنواع البيانات متوافقة مع JSON.
        """
        try:
            all_data = self.data_store.load_all_historical_data()
            if all_data.empty or len(all_data) < 2:
                logger.info("لا توجد بيانات كافية للمقارنة.")
                return []

            # 1. تحويل عمود التاريخ إلى صيغة datetime للتعامل معه بشكل صحيح
            all_data[C.SESSION_DATE_COLUMN_NAME] = pd.to_datetime(
                all_data[C.SESSION_DATE_COLUMN_NAME], dayfirst=True
            )

            alerts = []

            # 2. المرور على كل "أجل" (tenor) موجود في البيانات
            unique_tenors = all_data[C.TENOR_COLUMN_NAME].unique()

            for tenor in unique_tenors:
                # 3. فلترة البيانات لعزل بيانات هذا الأجل فقط وترتيبها من الأحدث للأقدم
                tenor_data = all_data[
                    all_data[C.TENOR_COLUMN_NAME] == tenor
                ].sort_values(by=C.SESSION_DATE_COLUMN_NAME, ascending=False)

                # 4. التأكد من وجود جلستين على الأقل للمقارنة
                if len(tenor_data) < 2:
                    continue

                # 5. تحديد آخر جلستين لهذا الأجل
                latest_entry = tenor_data.iloc[0]
                previous_entry = tenor_data.iloc[1]

                latest_yield = latest_entry[C.YIELD_COLUMN_NAME]
                previous_yield = previous_entry[C.YIELD_COLUMN_NAME]

                if previous_yield == 0:
                    continue

                # 6. حساب نسبة التغير
                change = ((latest_yield - previous_yield) / previous_yield) * 100

                # 7. إنشاء تنبيه إذا كان التغير يتجاوز الحد المسموح به
                if abs(change) >= threshold:
                    direction = "زيادة" if change > 0 else "انخفاض"
                    alerts.append(
                        {
                            "tenor": int(tenor),
                            "latest_yield": float(latest_yield),
                            "previous_yield": float(previous_yield),
                            "change_percent": float(change),
                            "direction": direction,
                            # استخدام التواريخ الفعلية من البيانات
                            "latest_date": latest_entry[
                                C.SESSION_DATE_COLUMN_NAME
                            ].strftime("%d/%m/%Y"),
                            "previous_date": previous_entry[
                                C.SESSION_DATE_COLUMN_NAME
                            ].strftime("%d/%m/%Y"),
                        }
                    )
            return alerts

        except Exception as e:
            logger.error(f"خطأ في اكتشاف تغييرات العوائد: {str(e)}", exc_info=True)
            return []

    def clear_all_data(self):
        """مسح جميع البيانات"""
        self.data_store.clear_all_data()


# ==============================================================================
# ^^^^^^^^^^^^^^^^^^^^^^^^  نهاية الجزء الذي تم تعديله  ^^^^^^^^^^^^^^^^^^^^^^^^^^
# ==============================================================================


class AuthSystem:
    def __init__(self):
        self.ph = PasswordHasher()
        self.master_pass = os.environ.get(
            "ADMIN_PANEL_PASSWORD", "default-password-for-testing"
        )
        if not self.master_pass:
            logger.critical(
                "FATAL: ADMIN_PANEL_PASSWORD environment variable is not set!"
            )
            raise ValueError("Admin password is not configured.")
        self.encrypted_pass = self.ph.hash(self.master_pass)

    def verify(self, input_pass: str) -> bool:
        """التحقق من كلمة المرور"""
        try:
            if not self.encrypted_pass or not isinstance(self.encrypted_pass, str):
                return False
            self.ph.verify(self.encrypted_pass, input_pass)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False


class UIManager:
    @staticmethod
    def render_header(title: str, icon: str = ""):
        st.markdown(
            f"""
            <div class='admin-header'>
                <h3>{icon} {title}</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )

    @staticmethod
    def render_session_timer(remaining: int):
        st.markdown(
            f"""
            <div class='admin-session-timer'>
                ⏰ تنتهي بعد: <strong>{remaining}</strong> ثانية
            </div>
            """,
            unsafe_allow_html=True,
        )

    @staticmethod
    def render_metric(label: str, value: str):
        st.markdown(
            f"""
            <div class='admin-metric'>
                <strong>{label}:</strong> {value}
            </div>
            """,
            unsafe_allow_html=True,
        )

    @staticmethod
    def render_alert_result(result: dict):
        status = result.get("status", "error")
        message = result.get("message", "خطأ غير معروف")

        status_map = {
            "success": "success",
            "warning": "warning",
            "error": "error",
            "info": "info",
        }
        status_class = status_map.get(status, "default")

        st.markdown(
            f"""
            <div class='admin-alert admin-alert--{status_class}'>
                {message}
            </div>
            """,
            unsafe_allow_html=True,
        )


class SecretAdminPanel:
    def __init__(self, data_store):
        self.data_store = data_store
        self.alert_manager = AlertManager()
        self.db_manager = DatabaseManager(data_store)
        self.auth = AuthSystem()
        self.ui = UIManager()
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self._init_session()

    def _init_session(self):
        if "panel_active" not in st.session_state:
            st.session_state.update(
                {
                    "panel_active": False,
                    "panel_expiry": 0,
                    "attempts": 0,
                    "password_requested": False,
                }
            )

    def _render_login(self):
        """عرض صفحة تسجيل الدخول"""
        if st.button("🔒", key="secret_button"):
            st.session_state.panel_clicks = st.session_state.get("panel_clicks", 0) + 1
            if st.session_state.panel_clicks >= 1:
                st.session_state.password_requested = True
                st.rerun()

        if st.session_state.get("password_requested", False):
            password = st.text_input("كلمة المرور:", type="password")
            if st.button("تسجيل الدخول"):
                if self.auth.verify(password):
                    st.session_state.panel_active = True
                    st.session_state.panel_expiry = time.time() + PANEL_TIMEOUT
                    st.success("تم تفعيل اللوحة!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.session_state.attempts += 1
                    remaining = MAX_LOGIN_ATTEMPTS - st.session_state.attempts
                    if st.session_state.attempts >= MAX_LOGIN_ATTEMPTS:
                        st.error("تم تجاوز الحد الأقصى لمحاولات الدخول")
                        return True
                    st.error(f"خطأ! {remaining} محاولة متبقية")
        return False

    def _render_tabs(self):
        """عرض تبويبات اللوحة"""
        tab1, tab2, tab3, tab4 = st.tabs(
            ["⚙️ النظام", "🗃️ قاعدة البيانات", "📱 تليجرام", "⚠️ خطر"]
        )

        with tab1:
            self._render_system_tab()
        with tab2:
            self._render_database_tab()
        with tab3:
            self._render_telegram_tab()
        with tab4:
            self._render_danger_tab()

    def _render_system_tab(self):
        """تبويب النظام"""
        self.ui.render_header("🔧 معلومات النظام", "🔧")
        remaining = max(0, int(st.session_state.panel_expiry - time.time()))
        self.ui.render_metric(
            "حالة الجلسة", "نشطة ✅" if st.session_state.panel_active else "غير نشطة ❌"
        )
        self.ui.render_metric("الوقت المتبقي", f"{remaining} ثانية")

        st.markdown("### 📡 اختبار الاتصالات")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔍 اختبار قاعدة البيانات", use_container_width=True):
                with st.spinner("جاري الاختبار..."):
                    if self.db_manager.get_latest_data().empty:
                        st.error("❌ لا توجد بيانات")
                    else:
                        st.success("✅ قاعدة البيانات متاحة")

        with col2:
            if st.button("📱 اختبار تليجرام", use_container_width=True):
                if not self.telegram_token or not self.telegram_chat_id:
                    st.error("❌ إعدادات تليجرام غير مكتملة")
                else:
                    try:
                        response = requests.get(
                            f"https://api.telegram.org/bot{self.telegram_token}/getMe",
                            timeout=5,
                        )
                        if response.ok:
                            st.success("✅ اتصال تليجرام نشط")
                        else:
                            st.error(f"❌ فشل الاتصال: {response.status_code}")
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Telegram connection test failed: {e}")
                        st.error("❌ خطأ في الاتصال")

        st.markdown("### 🚀 التحديث الشامل")
        st.info("تشغيل اسكريبت التحديث لجلب أحدث البيانات")

        if st.button("🚀 تشغيل التحديث", type="primary", use_container_width=True):
            with st.spinner("جاري التحديث..."):
                try:
                    process = subprocess.Popen(
                        [sys.executable, "update_data.py", "--force-refresh"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    stdout, stderr = process.communicate(timeout=300)

                    if process.returncode == 0:
                        st.success("✅ تم التحديث بنجاح!")
                        with st.expander("📄 سجل التحديث"):
                            st.code(stdout, language="log")
                    else:
                        st.error("❌ فشل التحديث")
                        with st.expander("🔍 التفاصيل"):
                            st.code(stderr, language="log")
                except Exception as e:
                    st.error(f"❌ خطأ: {str(e)}")

    def _render_database_tab(self):
        """تبويب قاعدة البيانات"""
        self.ui.render_header("🗃️ إدارة قاعدة البيانات", "🗃️")

        try:
            data = self.db_manager.get_all_data()

            stats = {
                "إجمالي السجلات": len(data),
                "أحدث تاريخ": self.data_store.get_latest_session_date() or "غير متوفر",
            }
            for k, v in stats.items():
                self.ui.render_metric(k, str(v))

            conn_uri = os.environ.get("POSTGRES_URI", "")
            if conn_uri:
                masked = (
                    conn_uri.split("@")[-1].split("/")[0]
                    if "://" in conn_uri
                    else "****"
                )
                st.markdown(f"**الخادم:** {masked}")

            if not data.empty:
                st.markdown("### 📊 البيانات")
                st.dataframe(data.head(50), use_container_width=True)

                csv = data.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 تنزيل CSV",
                    data=csv,
                    file_name="treasury_data.csv",
                    mime="text/csv",
                )
            else:
                st.info("لا توجد بيانات")

        except Exception as e:
            logger.error(f"خطأ في عرض تبويب قاعدة البيانات: {e}", exc_info=True)
            st.error(f"❌ خطأ في عرض البيانات: {str(e)}")

    def _render_telegram_tab(self):
        """تبويب تليجرام"""
        self.ui.render_header("📱 تنبيهات تليجرام", "📱")

        if not self.telegram_token or not self.telegram_chat_id:
            st.warning("⚠️ إعدادات تليجرام غير مكتملة")
            with st.expander("دليل الإعداد"):
                st.markdown("""
                    1. إنشاء بوت تليجرام من BotFather
                    2. أرسل رسالة للبوت الجديد
                    3. احصل على chat_id من خلال:
                       https://api.telegram.org/botYOUR_TOKEN/getUpdates
                    4. أضف المتغيرات في ملف .env
                    """)
            return

        stats = self.alert_manager.get_stats()
        st.markdown(f"**التنبيهات المخزنة:** {stats['total_alerts']}")

        if st.button("🗑️ مسح كاش التنبيهات", use_container_width=True):
            if self.alert_manager.clear_cache():
                st.success("تم المسح بنجاح")
                st.rerun()

        st.markdown("---")

        st.info(
            "**الإرسال العادي:** يرسل التنبيهات الجديدة فقط التي لم يتم إرسالها من قبل."
        )
        if st.button("🔍 فحص وإرسال التنبيهات الجديدة", use_container_width=True):
            with st.spinner("جاري فحص التنبيهات الجديدة..."):
                threshold = float(os.environ.get("ALERTS_THRESHOLD", "0.5"))
                alerts = self.db_manager.check_yield_changes(threshold)

                if not alerts:
                    st.info("لا توجد تغييرات.")
                    return

                new_alerts = [
                    a for a in alerts if not self.alert_manager.is_duplicate(a)
                ]

                if not new_alerts:
                    st.success(
                        "✅ لا توجد تنبيهات جديدة لإرسالها. البيانات لم تتغير بشكل كبير."
                    )
                    return

                success = 0
                for alert in new_alerts:
                    message = self._generate_alert_message(alert)
                    if self._send_telegram(message):
                        self.alert_manager.mark_sent(alert)
                        success += 1

                st.success(
                    f"تم إرسال {success} من أصل {len(new_alerts)} تنبيه جديد بنجاح."
                )

        st.markdown("---")

        st.warning(
            "⚠️ **إرسال إجباري:** هذا الزر سيتجاهل ذاكرة التخزين المؤقت ويرسل جميع التغييرات المكتشفة حاليًا، حتى لو تم إرسالها من قبل."
        )
        if st.button(
            "🚀 إرسال إجباري لجميع التنبيهات", type="primary", use_container_width=True
        ):
            with st.spinner("جاري الفحص والإرسال الإجباري..."):
                try:
                    # استخدمنا 0.0 كحد أدنى لإرسال كل التغيرات
                    alerts = self.db_manager.check_yield_changes(0.0)

                    if not alerts:
                        st.info("لا توجد تغييرات ليتم إرسالها.")
                    else:
                        success_count = 0
                        for alert in alerts:
                            message = self._generate_alert_message(alert)
                            if self._send_telegram(message):
                                self.alert_manager.mark_sent(alert)
                                success_count += 1

                        st.success(f"✅ تم إرسال {success_count} تنبيه بشكل إجباري.")
                except Exception as e:
                    st.error(f"⚠️ حدث خطأ أثناء الإرسال الإجباري: {e}")

    def _generate_alert_message(self, alert: dict) -> str:
        """توليد رسالة تنبيه"""
        emoji = "📈" if alert["direction"] == "زيادة" else "📉"
        return f"""
        {emoji} *تنبيه تغيير العائد* *الأجل:* {alert['tenor']} يوم
        *التاريخ الحالي:* {alert['latest_date']}
        *التاريخ السابق:* {alert['previous_date']}

        *العائد الحالي:* {alert['latest_yield']:.3f}%
        *العائد السابق:* {alert['previous_yield']:.3f}%

        *{alert['direction']}:* {abs(alert['change_percent']):.3f}%
        🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """

    def _send_telegram(self, message: str) -> bool:
        """إرسال رسالة تليجرام"""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning(
                "Telegram token or chat_id not configured. Cannot send message."
            )
            return False

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            return response.ok
        except requests.exceptions.RequestException as e:
            logger.error(f"خطأ في إرسال تليجرام: {str(e)}")
            return False

    def _render_danger_tab(self):
        """تبويب منطقة الخطر"""
        self.ui.render_header("⚠️ العمليات الحساسة", "⚠️")
        st.warning("⚠️ هذا الإجراء لا يمكن التراجع عنه!")

        user_input = st.text_input("اكتب 'امسح كل شيء' للتأكيد:", key="confirm").strip()
        if st.button("🚫 مسح جميع البيانات", disabled=(user_input != "امسح كل شيء")):
            try:
                self.db_manager.clear_all_data()
                st.success("تم المسح بنجاح!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ خطأ: {str(e)}")


def render_secret_admin_panel(data_store):
    """الدالة الرئيسية لعرض لوحة التحكم"""
    if os.environ.get("ENABLE_ADMIN_PANEL", "true").lower() != "true":
        return

    try:
        panel = SecretAdminPanel(data_store)
        is_active = st.session_state.get("panel_active", False)
        expiry_time = st.session_state.get("panel_expiry", 0)

        if is_active and time.time() > expiry_time:
            st.session_state.panel_active = False
            st.rerun()
            return

        if st.session_state.get("panel_active", False):
            panel._render_tabs()
        else:
            panel._render_login()

    except Exception as e:
        logger.error(f"خطأ في عرض اللوحة: {str(e)}", exc_info=True)
        st.error(f"حدث خطأ فادح في لوحة التحكم: {e}")


if __name__ == "__main__":

    class MockDataStore:
        def load_latest_data(self):
            return (
                pd.DataFrame(
                    {
                        "session_date": [datetime.now().strftime("%d/%m/%Y")],
                        "tenor": [91],
                        "yield": [5.1],
                    }
                ),
                None,
            )

        def load_all_historical_data(self):
            df = pd.DataFrame(
                {
                    "session_date": [
                        (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y"),
                        (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y"),
                        datetime.now().strftime("%d/%m/%Y"),
                    ],
                    "tenor": [91, 91, 91],
                    "yield": [4.9, 5.0, 5.1],
                }
            )
            return df

        def get_latest_session_date(self):
            return datetime.now().strftime("%Y-%m-%d")

        def clear_all_data(self):
            logger.info("Mock clear_all_data called.")
            pass

    st.set_page_config(layout="wide")
    render_secret_admin_panel(MockDataStore())
