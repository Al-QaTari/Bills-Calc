"""
update_data.py
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import platform
import sys
import subprocess
from datetime import datetime, timedelta, time
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional, List

import requests

# ---------------------------
# إعداد مسار المشروع بأمان
# ---------------------------
# أدخل مسار الملف الحالي (دليل المشروع) في بداية sys.path لضمان استيراد الملفات المحلية أولًا
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


# ---------------------------
# context manager لكتم Streamlit
# ---------------------------
@contextlib.contextmanager
def suppress_streamlit_warnings():
    """
    كتم مخرجات Streamlit عند التشغيل خارج بيئة Streamlit.
    افترضنا أن المتغير STREAMLIT_RUN يُعيّن إلى "true" عندما يكون داخل Streamlit.
    """
    run_flag = os.environ.get("STREAMLIT_RUN", "").lower()
    if run_flag == "true":
        # داخل Streamlit — لا تقم بالصّمت
        yield
    else:
        # خارجه — كتم المخرجات
        with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(
            devnull
        ), contextlib.redirect_stderr(devnull):
            yield


# ---------------------------
# استيرادات مع تحقّق ومرونة
# ---------------------------
SENTRY_AVAILABLE = False
DOTENV_AVAILABLE = False
CUSTOM_MODULES_AVAILABLE = False
DB_MANAGERS = {}

try:
    import importlib.util

    if importlib.util.find_spec("sentry_sdk") is not None:
        import sentry_sdk  # type: ignore

        SENTRY_AVAILABLE = True
except Exception:
    # سنسجّل التحذير لاحقًا عبر logger
    SENTRY_AVAILABLE = False

try:
    from dotenv import load_dotenv  # type: ignore

    DOTENV_AVAILABLE = True
except Exception:
    DOTENV_AVAILABLE = False

# حاول استيراد الوحدات المخصصة (قد تكون غير موجودة في بيئة التطوير المحلية)
CbeScraper = None
fetch_and_update_data_async = None
PostgresDBManager = None
SQLiteDBManager = None

try:
    from cbe_scraper import CbeScraper, fetch_and_update_data_async  # type: ignore
    from postgres_manager import PostgresDBManager  # type: ignore
    from db_manager import SQLiteDBManager  # type: ignore

    CUSTOM_MODULES_AVAILABLE = True
except Exception as e:
    # سنعرض رسالة عند التشغيل إذا كانت هذه الوحدات مطلوبة
    CUSTOM_MODULES_AVAILABLE = False
    missing_custom_modules_error = e  # للتشخيص لاحقًا

# ---------------------------
# إعداد logging
# ---------------------------
# حاول استخدام setup_logging من utils إذا متوفر، وإلا استخدم basicConfig
try:
    from utils import setup_logging  # type: ignore

    setup_logging(level=logging.INFO)
    # خفف مستوى تحذيرات Streamlit لو متوفر
    logging.getLogger("streamlit").setLevel(logging.ERROR)
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(
        logging.ERROR
    )
    logging.getLogger(
        "streamlit.runtime.scriptrunner_utils.script_run_context"
    ).setLevel(logging.ERROR)
except Exception:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

logger = logging.getLogger(__name__)

# ---------------------------
# ثوابت وإعدادات عامة
# ---------------------------
_FAILURE_COUNT = 0
_MAX_FAILURES = 5

ALERT_CACHE_FILE = PROJECT_DIR / "sent_alerts_cache.json"
CACHE_DURATION = 24  # ساعات
# session واحد لإعادة استخدام الاتصالات
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "cbe-updater/1.0"})


# ---------------------------
# أدوات إدارة كاش التنبيهات
# ---------------------------
class AlertManager:
    def __init__(self, cache_file: Path = ALERT_CACHE_FILE):
        self.cache_file = cache_file
        self._inproc_lock = (
            asyncio.Lock()
        )  # لحماية الكتابة داخل نفس العملية عند الاستخدام async
        self.cache: Dict[str, Any] = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        try:
            if not self.cache_file.exists():
                return {"alerts": {}}
            with self.cache_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(
                f"تحذير: فشل قراءة كاش التنبيهات ({e}) — سيتم إعادة إنشاء الملف."
            )
            return {"alerts": {}}

    def _save_cache_atomic(self):
        """حفظ آمن: اكتب في ملف مؤقت ثم استبدل (atomic replace)"""
        try:
            tmp = self.cache_file.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            tmp.replace(self.cache_file)
        except Exception as e:
            logger.error(f"فشل حفظ كاش التنبيهات: {e}")

    async def save_cache(self):
        # حماية داخلية للكتابة إذا استُدعيت من سياق async متعدد
        async with self._inproc_lock:
            await asyncio.to_thread(self._save_cache_atomic)

    def _generate_hash(self, alert: Dict[str, Any]) -> str:
        try:
            cp = float(alert.get("change_percent") or 0)
        except (ValueError, TypeError):
            cp = 0.0
        tenor = str(alert.get("tenor") or "")
        ld = str(alert.get("latest_date") or "")
        pd = str(alert.get("previous_date") or "")
        key = f"{tenor}_{ld}_{pd}_{cp:.2f}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def _cleanup_old_entries(self):
        cutoff_time = datetime.now() - timedelta(hours=CACHE_DURATION)
        cleaned_alerts = {}
        for alert_hash, data in self.cache.get("alerts", {}).items():
            try:
                ts = data.get("timestamp")
                if not ts:
                    continue
                if datetime.fromisoformat(ts) > cutoff_time:
                    cleaned_alerts[alert_hash] = data
            except (KeyError, ValueError):
                continue
        self.cache["alerts"] = cleaned_alerts

    def is_duplicate(self, alert: Dict[str, Any]) -> bool:
        self._cleanup_old_entries()
        return self._generate_hash(alert) in self.cache.get("alerts", {})

    def mark_sent(self, alert: Dict[str, Any]):
        alert_hash = self._generate_hash(alert)
        self.cache.setdefault("alerts", {})[alert_hash] = {
            "timestamp": datetime.now().isoformat()
        }
        # كتابة متزامنة بسيطة (لا تنتظر هنا)
        try:
            self._save_cache_atomic()
        except Exception as e:
            logger.error(f"خطأ أثناء وسم التنبيه كمرسَل: {e}")


# ---------------------------
# توليد رسالة تليجرام (HTML-escaped)
# ---------------------------
def _generate_telegram_message(alert: Dict[str, Any]) -> str:
    emoji = "📈" if str(alert.get("direction") or "").strip() == "زيادة" else "📉"
    tenor = escape(str(alert.get("tenor") or ""))
    try:
        latest = float(alert.get("latest_yield") or 0.0)
    except (ValueError, TypeError):
        latest = 0.0
    try:
        prev = float(alert.get("previous_yield") or 0.0)
    except (ValueError, TypeError):
        prev = 0.0
    direction = escape(str(alert.get("direction") or ""))
    try:
        change = abs(float(alert.get("change_percent") or 0.0))
    except (ValueError, TypeError):
        change = 0.0

    return (
        f"{emoji} <b>تنبيه تغيير العائد</b>\n\n"
        f"<b>الأجل:</b> {tenor} يوم\n"
        f"<b>العائد الحالي:</b> {latest:.3f}% | <b>السابق:</b> {prev:.3f}%\n"
        f"<b>{direction}:</b> {change:.3f}%"
    )


# ---------------------------
# إرسال تنبيه تليجرام (مزامن) — يمكن استدعاؤه عبر asyncio.to_thread
# ---------------------------
def _send_telegram_alert_sync(alert: Dict[str, Any]) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error(
            "إعدادات تليجرام (TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID) غير موجودة."
        )
        return False

    message = _generate_telegram_message(alert)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        # استخدم session مُعَدّ مسبقًا
        response = HTTP_SESSION.post(url, json=payload, timeout=10)
        if response.ok:
            logger.info(f"✅ تم إرسال تنبيه تليجرام بنجاح للأجل: {alert.get('tenor')}")
            return True
        else:
            logger.error(
                f"❌ فشل إرسال تنبيه تليجرام: {response.status_code} - {response.text}"
            )
            return False
    except requests.RequestException as e:
        logger.error(f"❌ خطأ في الاتصال بتليجرام: {e}")
        return False


# نغلف دالة async لاستدعاء النسخة المتزامنة بدون حجب event loop
async def _send_telegram_alert(alert: Dict[str, Any]) -> bool:
    return await asyncio.to_thread(_send_telegram_alert_sync, alert)


# ---------------------------
# إرسال تنبيهات عامة (Sentry, Slack, Email placeholder)
# ---------------------------
def _send_alert(message: str, severity: str = "info"):
    """إرسال التنبيهات عبر Sentry و Slack"""
    # Sentry
    if SENTRY_AVAILABLE and os.environ.get("SENTRY_DSN"):
        try:
            sentry_sdk.capture_message(message, level=severity)
        except Exception as e:
            logger.error(f"خطأ في إرسال Sentry: {e}", exc_info=True)

    # Slack webhook (synchronous, استخدم session)
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if slack_webhook:
        try:
            color = (
                "#36a64f"
                if severity == "info"
                else ("#FFCC00" if severity == "warning" else "#FF0000")
            )
            payload = {
                "attachments": [
                    {
                        "color": color,
                        "title": "تحديث بيانات سندات الخزانة",
                        "text": message,
                        "footer": "نظام تحديث البيانات التلقائي",
                        "ts": int(datetime.now().timestamp()),
                    }
                ]
            }
            resp = HTTP_SESSION.post(slack_webhook, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"فشل إرسال تنبيه Slack: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"فشل إرسال تنبيه Slack: {e}", exc_info=True)

    # placeholder لإيميلات التنبيه (لم يُنفذ بعد)
    if os.environ.get("EMAIL_ALERTS", "").lower() == "true":
        logger.info("📧 إرسال الإيميل مفعل (لكن لم يُنفذ بعد).")


# ---------------------------
# عداد الأخطاء
# ---------------------------
def _increment_failure_count() -> int:
    global _FAILURE_COUNT
    _FAILURE_COUNT += 1
    logger.warning(f"⚠️ فشل في جلب البيانات (المحاولة {_FAILURE_COUNT}/{_MAX_FAILURES})")
    return _FAILURE_COUNT


def _reset_failure_count():
    global _FAILURE_COUNT
    _FAILURE_COUNT = 0
    logger.info("🔄 تم إعادة تعيين عداد الفشل بعد التحديث الناجح")


# ---------------------------
# حساب وقت التحديث التالي (منقح)
# ---------------------------
def _next_business_date(start_date: datetime.date) -> datetime.date:
    """
    إعادة أول يوم عمل (الافتراض: يوم العمل هو Sun-Thu => أيام الأسبوع 0..6: Mon=0)
    ولكن الكود السابق اعتبر الجمعة والسبت عطلة (4 و5) — نترك نفس الفرضية:
    هنا نعتبر أيام العطلة هي 4 (Friday) و5 (Saturday).
    """
    candidate = start_date
    while candidate.weekday() in [4, 5]:
        candidate += timedelta(days=1)
    return candidate


def calculate_next_update_time() -> datetime:
    """حساب وقت التحديث التالي — نسخة مُصححة وأكثر ثباتًا"""
    now = datetime.now()
    today = now.date()

    # إذا اليوم ليس يوم عمل (Fri/Sat) فارجع أول يوم عمل لاحق في الساعة 09:00
    if today.weekday() in [4, 5]:
        next_bd = _next_business_date(today + timedelta(days=1))
        return datetime.combine(next_bd, time(9, 0))

    market_open = time(9, 0)
    market_close = time(15, 0)

    if now.time() < market_open:
        return datetime.combine(today, market_open)
    elif now.time() >= market_close:
        # حدد أول يوم عمل التالي
        next_day = today + timedelta(days=1)
        next_bd = _next_business_date(next_day)
        return datetime.combine(next_bd, market_open)

    # خلال ساعات السوق
    try:
        # ✅ تم التعديل: اختيار أول مدير قاعدة بيانات متوفر للتحقق
        db_adapter = DB_MANAGERS.get("primary") or DB_MANAGERS.get("fallback")
        if (
            db_adapter
            and CUSTOM_MODULES_AVAILABLE
            and hasattr(db_adapter, "get_latest_session_date")
        ):
            latest_date = db_adapter.get_latest_session_date()
            if latest_date:
                # افترض latest_date في شكل "DD/MM/YYYY"
                try:
                    latest_dt = datetime.strptime(latest_date, "%d/%m/%Y")
                    if latest_dt.date() == today:
                        if hasattr(db_adapter, "get_daily_update_count"):
                            update_count = db_adapter.get_daily_update_count()
                            base_interval = 60
                            interval = max(15, base_interval - (update_count * 10))
                            return now + timedelta(minutes=interval)
                        else:
                            return now + timedelta(minutes=30)
                    else:
                        return now
                except Exception:
                    # لو فشل التحويل نرجع بعد 30 دقيقة
                    return now + timedelta(minutes=30)
            else:
                return now + timedelta(minutes=30)
    except Exception as e:
        logger.error(f"خطأ في حساب وقت التحديث التالي (DB): {e}", exc_info=True)
        return now + timedelta(minutes=30)

    return now + timedelta(minutes=30)


# ---------------------------
# دالة جلب وتحديث البيانات (آمنة)
# ---------------------------
async def safe_fetch_and_update(
    scraper_adapter, db_adapter, force_refresh: bool = False
):
    """
    دالة async لجلب وتحديث البيانات مع timeout ومعالجة الأخطاء.
    تفترض أن fetch_and_update_data_async موجود ومعمول بشكل async.
    """
    if fetch_and_update_data_async is None:
        raise RuntimeError(
            "fetch_and_update_data_async غير متوفر — تأكد من وجود cbe_scraper.py"
        )

    try:
        result = await asyncio.wait_for(
            fetch_and_update_data_async(
                data_source=scraper_adapter,
                data_store=db_adapter,
                status_callback=lambda msg: logger.info(f"📌 {msg}"),
                force_refresh=force_refresh,
            ),
            timeout=180.0,
        )
        return result
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError("تجاوز الوقت المسموح لجلب البيانات (3 دقائق)")
    except Exception as e:
        logger.error(f"خطأ في جلب البيانات: {e}", exc_info=True)
        raise


# ---------------------------
# التحقق من متغيرات البيئة (مرن)
# ---------------------------
def _check_required_env_vars():
    """
    لا نفرض POSTGRES_URI لأن لدينا SQLite كفشل احتياطي.
    إن وُجد SENTRY_DSN فمن المستحسن وضع SENTRY_ENVIRONMENT لكن لا نجبر عليه.
    """
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn and not os.environ.get("SENTRY_ENVIRONMENT"):
        logger.warning(
            "SENTRY_DSN موجود لكن SENTRY_ENVIRONMENT غير محدد — سيتم استخدام 'production' افتراضيًا."
        )


# ---------------------------
# تهيئة الخدمات (Sentry + DB adapter)
# ---------------------------
def _initialize_services() -> List[Any]:
    """
    ✅ تم التعديل: تهيئة مديري قواعد البيانات.
    - يحاول تهيئة PostgreSQL كـ 'primary'
    - يحاول تهيئة SQLite كـ 'fallback'
    - يُرجع قائمة بالمديرين الذين تم تهيئتهم بنجاح.
    """
    # Sentry
    sentry_dsn = os.environ.get("SENTRY_DSN")
    sentry_env = os.environ.get("SENTRY_ENVIRONMENT", "production")
    if sentry_dsn and SENTRY_AVAILABLE:
        try:
            sentry_sdk.init(
                dsn=sentry_dsn, traces_sample_rate=1.0, environment=sentry_env
            )
            logger.info("✅ تم تهيئة Sentry بنجاح")
        except Exception as e:
            logger.error(f"❌ فشل تهيئة Sentry: {e}", exc_info=True)

    adapters = []

    # محاولة تهيئة PostgreSQL كقاعدة بيانات رئيسية
    if os.environ.get("POSTGRES_URI") and PostgresDBManager is not None:
        try:
            postgres_adapter = PostgresDBManager()
            adapters.append(postgres_adapter)
            logger.info("📊 استخدام قاعدة البيانات PostgreSQL (رئيسي)")
        except Exception as e:
            logger.warning(f"❌ فشل تهيئة PostgreSQL: {e}", exc_info=True)

    # محاولة تهيئة SQLite كخيار احتياطي (مُتاح دائمًا)
    if SQLiteDBManager is not None:
        try:
            sqlite_adapter = SQLiteDBManager()
            adapters.append(sqlite_adapter)
            logger.info("📊 استخدام قاعدة البيانات SQLite المحلية (احتياطي)")
        except Exception as e:
            logger.error(f"❌ فشل تهيئة SQLiteDBManager: {e}", exc_info=True)

    if not adapters:
        raise RuntimeError("لا يمكن العثور على مدير قاعدة بيانات مناسب")

    # قم بتعيين المديرين في القاموس العام للوصول إليها في calculate_next_update_time
    DB_MANAGERS["primary"] = (
        adapters[0] if adapters and isinstance(adapters[0], PostgresDBManager) else None
    )
    DB_MANAGERS["fallback"] = (
        adapters[0]
        if adapters
        and isinstance(adapters[0], SQLiteDBManager)
        and not DB_MANAGERS["primary"]
        else (adapters[1] if len(adapters) > 1 else None)
    )

    return adapters


# ---------------------------
# معالجة نتيجة التحديث (blocking) — سننفذها في thread لتجنب حجب الـ event loop
# ---------------------------
def _process_update_result_blocking(updated: Optional[bool], db_adapter):
    """
    معالجة نتائج التحديث — دالة متزامنة لأنها تتصل بقاعدة البيانات وتستخدم requests.
    عند الاستخدام داخل الكود async يجب استدعاؤها عبر asyncio.to_thread(...)
    """
    try:
        if updated is False:
            latest_date = db_adapter.get_latest_session_date()
            gaps = db_adapter.detect_data_gaps()
            if latest_date:
                try:
                    last_date = datetime.strptime(latest_date, "%d/%m/%Y")
                except Exception:
                    logger.warning(
                        "تعذر تحويل latest_date إلى datetime — تجاهل الحسابات المتعلقة بالزمن."
                    )
                    last_date = None

                days_since_update = (
                    (datetime.now() - last_date).days if last_date else None
                )
                gap_status = ""

                if gaps:
                    total_missing = sum(gap.get("gap_length", 0) for gap in gaps)
                    gap_status = (
                        f" | فجوات: {len(gaps)} فجوة، {total_missing} يوم مفقود"
                    )

                if days_since_update == 0:
                    status, log_level = "محدث اليوم", logging.INFO
                elif days_since_update is not None and days_since_update <= 7:
                    status, log_level = (
                        f"محدث قبل {days_since_update} يوم",
                        logging.INFO,
                    )
                elif days_since_update is not None and days_since_update <= 10:
                    status, log_level = (
                        f"تحديث قديم (قبل {days_since_update} يوم)",
                        logging.WARNING,
                    )
                else:
                    status, log_level = (
                        f"تحديث متأخر ({days_since_update} يوم)",
                        logging.ERROR,
                    )

                logger.log(
                    log_level,
                    f"ℹ️ البيانات {status}{gap_status} | أحدث تاريخ: {latest_date}",
                )

                if log_level >= logging.WARNING and datetime.now().weekday() in [
                    3,
                    6,
                ]:  # الخميس والأحد فقط
                    _send_alert(
                        f"تحديث متأخر: البيانات محدثة حتى {latest_date} (مر {days_since_update} يوم دون تحديث){gap_status}",
                        severity=(
                            "warning" if log_level == logging.WARNING else "critical"
                        ),
                    )
            else:
                logger.warning("⚠️ لا توجد بيانات في قاعدة البيانات بعد")
                _send_alert("لا توجد بيانات في قاعدة البيانات بعد", severity="warning")

            # استدعاء دالة فحص التنبيهات دائمًا
            _check_and_send_telegram_alerts_blocking(db_adapter)

        elif updated is True:
            logger.info("✅ تم تحديث البيانات بنجاح.")
            _reset_failure_count()
            next_update = calculate_next_update_time()
            logger.info(
                f"⏰ سيتم التحديث التالي في: {next_update.strftime('%Y-%m-%d %H:%M')}"
            )
            # فحص وإرسال تنبيهات تليجرام (قد يكون blocking لذا يجب تشغيله داخل thread)
            _check_and_send_telegram_alerts_blocking(db_adapter)

        elif updated is None:
            logger.error("❌ فشل في تحديث البيانات - خطأ غير متوقع")
            _send_alert("فشل غير متوقع في تحديث البيانات", severity="critical")
        else:
            logger.info("ℹ️ لا توجد بيانات جديدة للتحديث.")
            _check_and_send_telegram_alerts_blocking(db_adapter)
    except Exception as e:
        logger.error(f"❌ خطأ أثناء معالجة نتيجة التحديث: {e}", exc_info=True)


# ---------------------------
# فحص وإرسال تنبيهات تليجرام (blocking) — تستدعى داخل thread
# ---------------------------
def _check_and_send_telegram_alerts_blocking(db_adapter):
    alerts_enabled = os.environ.get("ALERTS_ENABLED", "true").lower() == "true"
    if not alerts_enabled:
        logger.info("🚫 تم تعطيل إرسال تنبيجرام عبر متغيرات البيئة.")
        return

    logger.info("ℹ️ بدء فحص تغييرات العائد لإرسال تنبيجرام...")
    try:
        manager = AlertManager()
        threshold = float(os.environ.get("ALERTS_THRESHOLD", "0.5"))

        # ✅ تم التعديل: استخدام db_adapter الذي تم تمريره
        alerts = db_adapter.check_yield_changes(threshold_percent=threshold)

        if not alerts:
            logger.info("👍 لا توجد تغييرات كبيرة في العائد تستدعي إرسال تنبيه.")
            return

        new_alerts = [a for a in alerts if not manager.is_duplicate(a)]
        if not new_alerts:
            logger.info("ℹ️ التغييرات المكتشفة تم إرسالها من قبل.")
            return

        logger.info(f"🔔 يوجد {len(new_alerts)} تنبيه جديد سيتم إرساله...")
        success_count = 0
        for alert in new_alerts:
            if _send_telegram_alert_sync(alert):
                manager.mark_sent(alert)
                success_count += 1
        logger.info(f"🚀 تم إرسال {success_count} تنبيه جديد بنجاح.")
    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيهات التليجرام تلقائيًا: {e}", exc_info=True)


# ---------------------------
# دالة لضمان تثبيت Playwright
# ---------------------------
def _ensure_playwright_is_installed_for_cron():
    """
    تضمن تثبيت متصفح Playwright. هذا ضروري للبيئات التي لا يمكن التحكم فيها مثل مهام cron.
    """
    try:
        logger.info(
            "Ensuring Playwright browser is installed for the cron job (no-deps)..."
        )
        # لا نستخدم --with-deps لأن البيئة لا تسمح بـ sudo
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 دقائق
            check=False,
        )
        if result.returncode == 0:
            logger.info("✅ Playwright browser installed/verified successfully.")
            return True
        else:
            logger.warning(
                f"Playwright install command finished with code {result.returncode}."
            )
            logger.warning(f"STDOUT: {result.stdout}")
            logger.error(f"STDERR: {result.stderr}")
            return False
    except Exception as e:
        logger.error(
            f"❌ An unexpected error occurred during Playwright setup: {e}",
            exc_info=True,
        )
        return False


# ---------------------------
# الدالة الرئيسية (async)
# ---------------------------
async def main(force_refresh: bool):
    """الدالة الرئيسية للتحديث (async)"""
    # الخطوة الأولى: التأكد من تثبيت المتصفح
    _ensure_playwright_is_installed_for_cron()
    if not CUSTOM_MODULES_AVAILABLE:
        logger.error(
            f"❌ لا يمكن تشغيل السكريبت بدون المكتبات المطلوبة: {getattr(missing_custom_modules_error, 'args', missing_custom_modules_error)}"
        )
        raise RuntimeError("الموديلات المخصصة غير متاحة.")

    if DOTENV_AVAILABLE:
        load_dotenv()

    logger.info("📦 بدء مهمة التحديث المجدولة (Async)...")
    logger.info(f"🖥️ نظام التشغيل: {platform.system()} {platform.release()}")
    logger.info(f"🐍 إصدار Python: {platform.python_version()}")
    logger.info("=" * 60)

    try:
        _check_required_env_vars()
        # ✅ تم التعديل: تهيئة مديري قواعد البيانات
        adapters = _initialize_services()
        scraper_adapter = CbeScraper()

        logger.info(
            f"{'🔄' if force_refresh else '⏳'} جاري جلب البيانات {'مع تجاهل الكاش' if force_refresh else 'من الكاش'}..."
        )
        logger.info("📊 سيتم التحقق من التكرار قبل الحفظ لتجنب البيانات المكررة")

        updated = None
        save_success = False

        # ✅ تم التعديل هنا: منطق الحفظ المحسن - يحفظ فقط في قاعدة بيانات واحدة أولاً للتحقق من التكرار
        updated = None
        save_success = False

        # جرب أولاً مع أول قاعدة بيانات متاحة
        primary_adapter = adapters[0]
        try:
            updated_result = await safe_fetch_and_update(
                scraper_adapter, primary_adapter, force_refresh
            )

            if updated_result is True:
                logger.info(
                    f"✅ تم تحديث البيانات بنجاح في {type(primary_adapter).__name__}."
                )
                updated = True
                save_success = True

                # إذا تم التحديث بنجاح، احفظ في باقي قواعد البيانات
                for adapter in adapters[1:]:
                    try:
                        await safe_fetch_and_update(
                            scraper_adapter, adapter, force_refresh
                        )
                        logger.info(
                            f"✅ تم تحديث البيانات في {type(adapter).__name__} أيضاً."
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ فشل الحفظ في {type(adapter).__name__}: {e}",
                            exc_info=True,
                        )

            elif updated_result is False:
                logger.info(
                    f"ℹ️ البيانات مكررة في {type(primary_adapter).__name__} - لا حاجة للتحديث."
                )
                updated = False
                save_success = True

                # إذا كانت البيانات مكررة، لا نحتاج لحفظها في باقي قواعد البيانات

            else:
                logger.error(
                    f"❌ فشل في تحديث البيانات في {type(primary_adapter).__name__}."
                )
                save_success = False

        except Exception as e:
            logger.error(
                f"❌ فشل الحفظ في {type(primary_adapter).__name__}: {e}", exc_info=True
            )
            save_success = False

        if updated:
            # ✅ تم التعديل: نمرر أول adapter متاح للمراجعة
            logger.info("🎉 تم تحديث البيانات بنجاح!")
            await asyncio.to_thread(
                _process_update_result_blocking, updated, adapters[0]
            )
        elif not save_success:
            raise RuntimeError("❌ فشل الحفظ في جميع قواعد البيانات المتاحة.")
        else:
            # إذا لم يتم التحديث فعليًا (البيانات مكررة)، نستخدم أي محول متاح للتحقق
            logger.info("ℹ️ البيانات لم تتغير - لا حاجة للتحديث")
            await asyncio.to_thread(
                _process_update_result_blocking, updated, adapters[0]
            )

    except asyncio.TimeoutError as e:
        logger.error(f"⏰ {str(e)}")
        _increment_failure_count()
        if _FAILURE_COUNT >= _MAX_FAILURES:
            _send_alert(
                f"فشل التحديث {_MAX_FAILURES} مرات متتالية - توقف النظام",
                severity="critical",
            )
        raise
    except Exception as e:
        logger.error(f"❌ خطأ في جلب البيانات أو المعالجة: {e}", exc_info=True)
        _increment_failure_count()
        # سجل التفاصيل وأرسل تنبيه
        import traceback

        error_details = (
            f"❗ فشل التحديث المجدول: {e}\n\nتفاصيل:\n{traceback.format_exc()}"
        )
        logger.critical(error_details)
        if os.environ.get("SENTRY_DSN") and SENTRY_AVAILABLE:
            try:
                sentry_sdk.capture_exception(e)
            except Exception:
                pass
        _send_alert(f"فشل التحديث: {str(e)}", severity="critical")
        raise
    finally:
        logger.info("=" * 60)
        logger.info("🛑 انتهاء تنفيذ المهمة المجدولة.")


# ---------------------------
# دالة لتشغيل main بأمان (مع معالجة Windows event loop)
# ---------------------------
def run_main_safely(force_refresh: bool):
    """
    يشغّل الدالة الرئيسية مع معالجة خاصة لأنظمة Windows لسياسة الـ event loop.
    """

    if platform.system() == "Windows":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception as e:
            logger.warning(f"فشل تعيين event loop policy: {e}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main(force_refresh))
        except KeyboardInterrupt:
            print("\n⏹️ تم إيقاف السكريبت بواسطة المستخدم")
        finally:
            logger.info("🔄 تنظيف مهام asyncio...")
            try:
                tasks = asyncio.all_tasks(loop=loop)
                for task in tasks:
                    task.cancel()
                group = asyncio.gather(*tasks, return_exceptions=True)
                loop.run_until_complete(asyncio.wait_for(group, timeout=5.0))
            except asyncio.TimeoutError:
                logger.warning("⚠️ تجاوز الوقت المسموح به أثناء تنظيف المهام.")
            except Exception as e:
                logger.error(f"Error during asyncio cleanup: {e}", exc_info=True)
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)
    else:
        try:
            asyncio.run(main(force_refresh))
        except KeyboardInterrupt:
            print("\n⏹️ تم إيقاف السكريبت بواسطة المستخدم")
            sys.exit(0)


# ---------------------------
# CLI entrypoint
# ---------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update Treasury Bill data from CBE to your database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
أمثلة الاستخدام:
  python update_data.py                    # تحديث عادي
  python update_data.py --force-refresh    # تحديث مع تجاهل الكاش
  
متغيرات البيئة (يمكن استخدام PostgreSQL أو SQLite كبديل):
  POSTGRES_URI                 # (اختياري) رابط قاعدة البيانات PostgreSQL
  SENTRY_DSN                   # (اختياري) رابط Sentry للأخطاء  
  SLACK_WEBHOOK_URL            # (اختياري) رابط Slack للتنبيهات
  ALERTS_ENABLED               # (اختياري) تفعيل التنبيهات (افتراضي: true)
  ALERTS_THRESHOLD             # (اختياري) حد التنبيهات (افتراضي: 0.5)
  TELEGRAM_BOT_TOKEN           # (لاستيراد) توكن بوت تليجرام لإرسال التنبيهات
  TELEGRAM_CHAT_ID             # (لاستيراد) chat_id لاستقبال التنبيهات
        """,
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the cache and force a fresh data fetch from the website.",
    )
    args = parser.parse_args()

    print(f"🚀 بدء تشغيل السكريبت على {platform.system()}")
    print(f"🔧 معاملات التشغيل: force_refresh={args.force_refresh}")

    try:
        with suppress_streamlit_warnings():
            run_main_safely(force_refresh=args.force_refresh)
        print("✅ تم تشغيل السكريبت بنجاح")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n⏹️ تم إيقاف السكريبت بواسطة المستخدم")
        sys.exit(0)
    except Exception as e:
        print(f"💥 فشل تشغيل السكريبت: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


