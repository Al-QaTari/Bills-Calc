"""
Data update script for the Treasury Bills Calculator application.
سكريبت تحديث البيانات لتطبيق حاسبة أذون الخزانة.
"""

import os
import sys
import platform
import logging
import asyncio
import argparse
from datetime import datetime, timedelta, time
import requests
import hashlib
import json

# Add project path to support running from cron or docker directly
sys.path.append(os.getcwd())

# استيرادات مع معالجة الأخطاء
try:
    import importlib.util

    if importlib.util.find_spec("sentry_sdk") is not None:
        import sentry_sdk

        SENTRY_AVAILABLE = True
    else:
        SENTRY_AVAILABLE = False
except ImportError:
    print("⚠️ تحذير: sentry-sdk غير مثبت")
    SENTRY_AVAILABLE = False

try:
    from dotenv import load_dotenv

    DOTENV_AVAILABLE = True
except ImportError:
    print("⚠️ تحذير: python-dotenv غير مثبت")
    DOTENV_AVAILABLE = False

try:
    from cbe_scraper import CbeScraper, fetch_and_update_data_async
    from postgres_manager import PostgresDBManager
    from utils import setup_logging

    CUSTOM_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"❌ خطأ في استيراد المكتبات المخصصة: {e}")
    print("تأكد من أن جميع الملفات المطلوبة موجودة في نفس المجلد:")
    print("- cbe_scraper.py")
    print("- postgres_manager.py")
    print("- utils.py")
    print("- secret_admin_panel.py")
    CUSTOM_MODULES_AVAILABLE = False

# --- الكود المضاف لإخفاء التحذيرات ---
# ✅ FIX: تم إضافة هذا الجزء لإخفاء تحذيرات Streamlit غير الضرورية
# عند تشغيل الاسكريبت بشكل مستقل للحصول على مخرجات نظيفة.
try:
    from utils import setup_logging

    setup_logging(level=logging.INFO)
    logging.getLogger("streamlit").setLevel(logging.ERROR)
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(
        logging.ERROR
    )
    logging.getLogger(
        "streamlit.runtime.scriptrunner_utils.script_run_context"
    ).setLevel(logging.ERROR)
except (ImportError, Exception):
    # Fallback basic logging if setup_logging fails
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
# ------------------------------------

logger = logging.getLogger(__name__)

_FAILURE_COUNT = 0
_MAX_FAILURES = 5

# ==============================================================================
#  بداية الكود المضاف: أدوات إدارة وإرسال تنبيهات تليجرام
# ==============================================================================

ALERT_CACHE_FILE = "sent_alerts_cache.json"
CACHE_DURATION = 24  # عمر التنبيه في الكاش بالساعات


class AlertManager:
    def __init__(self):
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        try:
            if not os.path.exists(ALERT_CACHE_FILE):
                return {"alerts": {}}
            with open(ALERT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"alerts": {}}

    def _save_cache(self):
        with open(ALERT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def _generate_hash(self, alert: dict) -> str:
        key = f"{alert.get('tenor')}_{alert.get('latest_date')}_{alert.get('previous_date')}_{alert.get('change_percent', 0):.2f}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def _cleanup_old_entries(self):
        cutoff_time = datetime.now() - timedelta(hours=CACHE_DURATION)
        cleaned_alerts = {}
        for alert_hash, data in self.cache.get("alerts", {}).items():
            try:
                if datetime.fromisoformat(data["timestamp"]) > cutoff_time:
                    cleaned_alerts[alert_hash] = data
            except (KeyError, ValueError):
                continue
        self.cache["alerts"] = cleaned_alerts

    def is_duplicate(self, alert: dict) -> bool:
        self._cleanup_old_entries()
        return self._generate_hash(alert) in self.cache.get("alerts", {})

    def mark_sent(self, alert: dict):
        alert_hash = self._generate_hash(alert)
        self.cache["alerts"][alert_hash] = {"timestamp": datetime.now().isoformat()}
        self._save_cache()


def _generate_telegram_message(alert: dict) -> str:
    emoji = "📈" if alert.get("direction") == "زيادة" else "📉"
    return (
        f"{emoji} *تنبيه تغيير العائد*\n\n"
        f"*الأجل:* {alert.get('tenor')} يوم\n"
        f"*العائد الحالي:* {alert.get('latest_yield', 0):.3f}% | *السابق:* {alert.get('previous_yield', 0):.3f}%\n"
        f"*{alert.get('direction')}:* {abs(alert.get('change_percent', 0)):.3f}%"
    )


def _send_telegram_alert(alert: dict) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("إعدادات تليجرام (token or chat_id) غير موجودة.")
        return False

    message = _generate_telegram_message(alert)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.ok:
            logger.info(f"✅ تم إرسال تنبيه تليجرام بنجاح للأجل: {alert.get('tenor')}")
            return True
        else:
            logger.error(f"❌ فشل إرسال تنبيه تليجرام: {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"❌ خطأ في الاتصال بتليجرام: {e}")
        return False


# ==============================================================================
#  نهاية الكود المضاف
# ==============================================================================


def _send_alert(message: str, severity: str = "info"):
    """إرسال التنبيهات عبر Sentry و Slack"""
    # إرسال إلى Sentry إذا كان متوفراً
    if SENTRY_AVAILABLE:
        try:
            sentry_sdk.capture_message(message, level=severity)
        except Exception as e:
            logger.error(f"خطأ في إرسال Sentry: {e}")

    # إرسال إلى Slack إذا كان webhook متوفراً
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if slack_webhook:
        try:
            color = (
                "#36a64f"
                if severity == "info"
                else "#FFCC00" if severity == "warning" else "#FF0000"
            )
            response = requests.post(
                slack_webhook,
                json={
                    "attachments": [
                        {
                            "color": color,
                            "title": "تحديث بيانات سندات الخزينة",
                            "text": message,
                            "footer": "نظام تحديث البيانات التلقائي",
                            "ts": int(datetime.now().timestamp()),
                        }
                    ]
                },
                timeout=10,
            )
            if response.status_code != 200:
                logger.error(
                    f"فشل إرسال تنبيه Slack: {response.status_code} - {response.text}"
                )
        except Exception as e:
            logger.error(f"فشل إرسال تنبيه Slack: {str(e)}")

    if os.environ.get("EMAIL_ALERTS") == "true":
        logger.info("📧 إرسال الإيميل مفعل (لكن غير منفذ بعد)")


def _increment_failure_count() -> int:
    """زيادة عداد الفشل"""
    global _FAILURE_COUNT
    _FAILURE_COUNT += 1
    logger.warning(f"⚠️ فشل في جلب البيانات (المحاولة {_FAILURE_COUNT}/{_MAX_FAILURES})")
    return _FAILURE_COUNT


def _reset_failure_count():
    """إعادة تعيين عداد الفشل"""
    global _FAILURE_COUNT
    _FAILURE_COUNT = 0
    logger.info("🔄 تم إعادة تعيين عداد الفشل بعد التحديث الناجح")


def calculate_next_update_time() -> datetime:
    """حساب وقت التحديث التالي"""
    now = datetime.now()
    today = now.date()
    is_business_day = now.weekday() not in [4, 5]

    if not is_business_day:
        days_ahead = 7 - now.weekday() if now.weekday() == 5 else 6 - now.weekday()
        next_business_day = today + timedelta(days=days_ahead)
        return datetime.combine(next_business_day, time(9, 0))

    market_open = time(9, 0)
    market_close = time(15, 0)

    if now.time() < market_open:
        return datetime.combine(today, market_open)
    elif now.time() >= market_close:
        next_day = today + timedelta(days=1)
        while next_day.weekday() in [4, 5]:
            next_day += timedelta(days=1)
        return datetime.combine(next_day, market_open)

    try:
        if CUSTOM_MODULES_AVAILABLE:
            db_adapter = PostgresDBManager()
            latest_date = db_adapter.get_latest_session_date()

            if latest_date:
                if latest_date == now.strftime("%d/%m/%Y"):
                    update_count = db_adapter.get_daily_update_count()
                    base_interval = 60
                    interval = max(15, base_interval - (update_count * 10))
                    return now + timedelta(minutes=interval)
                else:
                    return now
            else:
                return now + timedelta(minutes=30)
    except Exception as e:
        logger.error(f"خطأ في حساب وقت التحديث التالي: {e}")
        return now + timedelta(minutes=30)


async def safe_fetch_and_update(scraper_adapter, db_adapter, force_refresh=False):
    """
    دالة لجلب وتحديث البيانات مع معالجة الأخطاء.
    """
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
        logger.error(f"خطأ في جلب البيانات: {e}")
        raise


def _check_required_env_vars():
    """التحقق من وجود متغيرات البيئة المطلوبة"""
    sentry_dsn = os.environ.get("SENTRY_DSN")
    required_env_vars = ["POSTGRES_URI"]
    if sentry_dsn:
        required_env_vars.append("SENTRY_ENVIRONMENT")

    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(
            f"❌ المتغيرات البيئية المطلوبة مفقودة: {', '.join(missing_vars)}"
        )


def _initialize_services():
    """تهيئة الخدمات مثل Sentry وقاعدة البيانات"""
    # تهيئة Sentry
    sentry_dsn = os.environ.get("SENTRY_DSN")
    sentry_env = os.environ.get("SENTRY_ENVIRONMENT", "production")
    if sentry_dsn and SENTRY_AVAILABLE:
        try:
            sentry_sdk.init(
                dsn=sentry_dsn,
                traces_sample_rate=1.0,
                environment=sentry_env,
            )
            logger.info("✅ تم تهيئة Sentry بنجاح")
        except Exception as e:
            logger.error(f"❌ فشل تهيئة Sentry: {e}")

    # تهيئة محول قاعدة البيانات
    if os.environ.get("POSTGRES_URI"):
        db_adapter = PostgresDBManager()
        logger.info("📊 استخدام قاعدة البيانات PostgreSQL")
    else:
        try:
            from db_manager import SQLiteDBManager

            db_adapter = SQLiteDBManager()
            logger.info("📊 استخدام قاعدة البيانات SQLite المحلية")
        except ImportError:
            logger.error("❌ لم يتم العثور على SQLiteDBManager")
            raise RuntimeError("لا يمكن العثور على مدير قاعدة بيانات مناسب")
    return db_adapter


def _process_update_result(updated, db_adapter):
    """معالجة نتيجة التحديث"""
    if updated is False:
        try:
            latest_date = db_adapter.get_latest_session_date()
            gaps = db_adapter.detect_data_gaps()

            if latest_date:
                last_date = datetime.strptime(latest_date, "%d/%m/%Y")
                days_since_update = (datetime.now() - last_date).days
                gap_status = ""

                if gaps:
                    total_missing = sum(gap["gap_length"] for gap in gaps)
                    gap_status = (
                        f" | فجوات: {len(gaps)} فجوة، {total_missing} يوم مفقود"
                    )

                if days_since_update == 0:
                    status, log_level = "محدث اليوم", logging.INFO
                elif days_since_update <= 2:
                    status, log_level = (
                        f"محدث قبل {days_since_update} يوم",
                        logging.INFO,
                    )
                elif days_since_update <= 5:
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

                if log_level >= logging.WARNING:
                    _send_alert(
                        f"تحديث متأخر: البيانات محدثة حتى {latest_date} "
                        f"(مر {days_since_update} يوم دون تحديث){gap_status}",
                        severity=(
                            "warning" if log_level == logging.WARNING else "critical"
                        ),
                    )
            else:
                logger.warning("⚠️ لا توجد بيانات في قاعدة البيانات بعد")
                _send_alert("لا توجد بيانات في قاعدة البيانات بعد", severity="warning")
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل حالة البيانات: {e}")

    elif updated is True:
        logger.info("✅ تم تحديث البيانات بنجاح.")
        _reset_failure_count()
        next_update = calculate_next_update_time()
        logger.info(
            f"⏰ سيتم التحديث التالي في: {next_update.strftime('%Y-%m-%d %H:%M')}"
        )
        _check_and_send_telegram_alerts(db_adapter)

    elif updated is None:
        logger.error("❌ فشل في تحديث البيانات - خطأ غير متوقع")
        _send_alert("فشل غير متوقع في تحديث البيانات", severity="critical")
    else:
        logger.info("ℹ️ لا توجد بيانات جديدة للتحديث.")


def _check_and_send_telegram_alerts(db_adapter):
    """فحص وإرسال تنبيهات تليجرام"""
    alerts_enabled = os.environ.get("ALERTS_ENABLED", "true").lower() == "true"
    if not alerts_enabled:
        logger.info("🚫 تم تعطيل إرسال تنبيهات تليجرام عبر متغيرات البيئة.")
        return

    logger.info("ℹ️ بدء فحص تغييرات العائد لإرسال تنبيهات تليجرام...")
    try:
        alert_manager = AlertManager()
        threshold = float(os.environ.get("ALERTS_THRESHOLD", "0.5"))
        alerts = db_adapter.check_yield_changes(threshold_percent=threshold)

        if not alerts:
            logger.info("👍 لا توجد تغييرات كبيرة في العائد تستدعي إرسال تنبيه.")
            return

        new_alerts = [a for a in alerts if not alert_manager.is_duplicate(a)]
        if not new_alerts:
            logger.info("ℹ️ التغييرات المكتشفة تم إرسالها من قبل.")
            return

        logger.info(f"🔔 يوجد {len(new_alerts)} تنبيه جديد سيتم إرساله...")
        success_count = 0
        for alert in new_alerts:
            if _send_telegram_alert(alert):
                alert_manager.mark_sent(alert)
                success_count += 1
        logger.info(f"🚀 تم إرسال {success_count} تنبيه جديد بنجاح.")

    except Exception as e:
        logger.error(f"❌ فشل إرسال تنبيهات التليجرام تلقائيًا: {str(e)}", exc_info=True)


async def main(force_refresh: bool):
    """الدالة الرئيسية للتحديث"""
    if not CUSTOM_MODULES_AVAILABLE:
        print("❌ لا يمكن تشغيل السكريبت بدون المكتبات المطلوبة")
        sys.exit(1)

    if DOTENV_AVAILABLE:
        load_dotenv()

    logger.info("📦 بدء مهمة التحديث المجدولة (Async)...")
    logger.info(f"🖥️ نظام التشغيل: {platform.system()} {platform.release()}")
    logger.info(f"🐍 إصدار Python: {platform.python_version()}")
    logger.info("=" * 60)

    try:
        _check_required_env_vars()
        db_adapter = _initialize_services()
        scraper_adapter = CbeScraper()

        logger.info(
            f"{'🔄' if force_refresh else '⏳'} جاري جلب البيانات {'مع تجاهل الكاش' if force_refresh else 'من الكاش'}..."
        )

        updated = await safe_fetch_and_update(
            scraper_adapter, db_adapter, force_refresh
        )
        _process_update_result(updated, db_adapter)

    except (asyncio.TimeoutError, Exception) as e:
        if isinstance(e, asyncio.TimeoutError):
            logger.error(f"⏰ {str(e)}")
            _increment_failure_count()
            if _FAILURE_COUNT >= _MAX_FAILURES:
                _send_alert(
                    f"فشل التحديث {_MAX_FAILURES} مرات متتالية - توقف النظام",
                    severity="critical",
                )
            sys.exit(1)
        else:
            logger.error(f"❌ خطأ في جلب البيانات: {str(e)}")
            _increment_failure_count()

        import traceback

        error_details = f"❗ فشل التحديث المجدول: {e}\n\nتفاصيل الخطأ الكاملة:\n{traceback.format_exc()}"
        logger.critical(error_details)
        print(f"❌ فشل في التحديث الشامل\n\n{error_details}")

        if os.environ.get("SENTRY_DSN") and SENTRY_AVAILABLE:
            sentry_sdk.capture_exception(e)

        _send_alert(f"فشل التحديث: {str(e)}", severity="critical")
        sys.exit(1)

    finally:
        logger.info("=" * 60)
        logger.info("🛑 انتهاء تنفيذ المهمة المجدولة.")


def run_main_safely(force_refresh: bool):
    """
    تشغيل الدالة الرئيسية بشكل آمن مع معالجة خاصة لـ Windows لحل مشكلة Playwright.
    """
    if platform.system() == "Windows":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception as e:
            logger.error(f"Failed to set event loop policy: {e}")

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
                logger.error(f"Error during asyncio cleanup: {e}")
            finally:
                loop.close()
                asyncio.set_event_loop(None)
    else:
        try:
            asyncio.run(main(force_refresh))
        except KeyboardInterrupt:
            print("\n⏹️ تم إيقاف السكريبت بواسطة المستخدم")
            sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update Treasury Bill data from CBE to your database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
أمثلة الاستخدام:
  python update_data.py                    # تحديث عادي
  python update_data.py --force-refresh    # تحديث مع تجاهل الكاش
  
متغيرات البيئة المطلوبة:
  POSTGRES_URI                 # رابط قاعدة البيانات
  SENTRY_DSN                   # (اختياري) رابط Sentry للأخطاء  
  SLACK_WEBHOOK_URL            # (اختياري) رابط Slack للتنبيهات
  ALERTS_ENABLED               # (اختياري) تفعيل التنبيهات (افتراضي: true)
  ALERTS_THRESHOLD             # (اختياري) حد التنبيهات (افتراضي: 0.5)
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
