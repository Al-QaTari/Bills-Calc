# cbe_scraper.py
import os
import sys
import pandas as pd
from io import StringIO
import asyncio
from typing import Optional, Callable, List, Dict, Any
import logging
from contextlib import contextmanager
import platform
import redis
import hashlib

# استيرادات محسنة مع معالجة أخطاء Windows
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ تحذير: Playwright غير مثبت - {e}")
    PLAYWRIGHT_AVAILABLE = False

try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    print("⚠️ تحذير: BeautifulSoup غير مثبت")
    BS4_AVAILABLE = False

try:
    from treasury_core.ports import YieldDataSource, HistoricalDataStore
    from enhanced_cache import EnhancedCache
    from backoff_retry import backoff_retry
    import constants as C
except ImportError as e:
    print(f"⚠️ تحذير: مكتبة مفقودة - {e}")

logger = logging.getLogger(__name__)


@contextmanager
def suppress_output():
    """
    Context manager to redirect stdout and stderr to devnull.
    """
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull
    try:
        yield
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        devnull.close()


class CbeScraper(YieldDataSource):
    def __init__(self):
        self.redis_client = None
        self.is_windows = platform.system() == "Windows"

        # التحقق من توفر المكتبات المطلوبة
        if not PLAYWRIGHT_AVAILABLE:
            logger.error(
                "❌ Playwright غير مثبت. قم بتشغيل: pip install playwright && playwright install chromium"
            )

        if not BS4_AVAILABLE:
            logger.error(
                "❌ BeautifulSoup غير مثبت. قم بتشغيل: pip install beautifulsoup4 lxml"
            )

        # إعداد Redis
        redis_uri = os.environ.get("AIVEN_REDIS_URI")
        if redis_uri:
            try:
                self.redis_client = redis.from_url(redis_uri, socket_timeout=10)
                # اختبار الاتصال
                self.redis_client.ping()
                logger.info("✅ Redis client initialized successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Redis client: {str(e)}")
                self.redis_client = None
        else:
            logger.warning("⚠️ AIVEN_REDIS_URI not set. Redis caching is disabled.")

        # إنشاء آلية التخزين المؤقت المحسنة
        try:
            self.cache = EnhancedCache(
                redis_client=self.redis_client,
                key_prefix="cbe_yields",
                base_ttl_seconds=6 * 60 * 60,  # 6 ساعات
                max_ttl_seconds=24 * 60 * 60,  # 24 ساعة
            )
        except Exception as e:
            logger.error(f"❌ فشل إنشاء نظام التخزين المؤقت: {e}")
            self.cache = None

    def _verify_page_structure(self, page_source: str) -> None:
        """
        التحقق من هيكل الصفحة.
        ✅ FIX: تم إزالة try/except للسماح بإظهار الخطأ RuntimeRrror عند فشل التحقق.
        هذا يجعل البرنامج أكثر قوة ويصلح الاختبار الفاشل.
        """
        essential_markers = getattr(
            C, "ESSENTIAL_TEXT_MARKERS", ["النتائج", "تاريخ الجلسة", "المقبولة"]
        )

        for marker in essential_markers:
            if marker not in page_source:
                raise RuntimeError(
                    f"Page structure verification failed! Marker '{marker}' not found."
                )

    def _parse_cbe_html(self, page_source: str) -> Optional[pd.DataFrame]:
        """تحليل HTML وإستخراج البيانات"""
        if not BS4_AVAILABLE:
            logger.error("❌ BeautifulSoup غير متوفر للتحليل")
            return None

        try:
            soup = BeautifulSoup(page_source, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(page_source, "html.parser")
            except Exception as e:
                logger.error(f"❌ فشل تحليل HTML: {e}")
                return None

        try:
            # البحث عن رؤوس النتائج
            results_headers = soup.find_all(
                lambda tag: tag.name == "h2" and "النتائج" in tag.get_text()
            )

            if not results_headers:
                logger.warning("⚠️ لم يتم العثور على رؤوس النتائج")
                return None

            all_dataframes = []

            for header in results_headers:
                try:
                    dates_table = header.find_next("table")
                    if not dates_table:
                        continue

                    dates_df = pd.read_html(StringIO(str(dates_table)))[0]
                    tenors = (
                        pd.to_numeric(dates_df.columns[1:], errors="coerce")
                        .dropna()
                        .astype(int)
                        .tolist()
                    )

                    session_dates_row = dates_df[dates_df.iloc[:, 0] == "تاريخ الجلسة"]
                    if session_dates_row.empty or not tenors:
                        continue

                    session_dates = session_dates_row.iloc[
                        0, 1 : len(tenors) + 1
                    ].tolist()

                    # إنشاء DataFrame للتواريخ والآجال
                    tenor_col = getattr(C, "TENOR_COLUMN_NAME", "tenor")
                    session_date_col = getattr(
                        C, "SESSION_DATE_COLUMN_NAME", "session_date"
                    )

                    dates_tenors_df = pd.DataFrame(
                        {
                            tenor_col: tenors,
                            session_date_col: session_dates,
                        }
                    )

                    # البحث عن جدول العروض المقبولة
                    accepted_bids_keyword = getattr(
                        C, "ACCEPTED_BIDS_KEYWORD", "المقبولة"
                    )
                    accepted_bids_header = header.find_next(
                        lambda tag: tag.name in ["p", "strong"]
                        and accepted_bids_keyword in tag.get_text()
                    )

                    if not accepted_bids_header:
                        continue

                    yields_table = accepted_bids_header.find_next("table")
                    if not yields_table:
                        continue

                    yields_df_raw = pd.read_html(StringIO(str(yields_table)))[0]
                    yields_df_raw.columns = ["البيان"] + tenors

                    yield_anchor_text = getattr(C, "YIELD_ANCHOR_TEXT", "العائد")
                    yield_row = yields_df_raw[
                        yields_df_raw.iloc[:, 0].str.contains(
                            yield_anchor_text, na=False
                        )
                    ]

                    if yield_row.empty:
                        continue

                    yield_series = yield_row.iloc[0, 1:].astype(float)
                    yield_col = getattr(C, "YIELD_COLUMN_NAME", "yield")
                    yield_series.name = yield_col

                    section_df = dates_tenors_df.join(yield_series, on=tenor_col)

                    if not section_df[yield_col].isnull().any():
                        all_dataframes.append(section_df)

                except Exception as e:
                    logger.warning(f"⚠️ خطأ في معالجة قسم: {e}")
                    continue

            if not all_dataframes:
                logger.warning("⚠️ لم يتم العثور على بيانات صالحة")
                return None

            final_df = pd.concat(all_dataframes, ignore_index=True)

            # معالجة التواريخ
            try:
                # تحويل التواريخ من تنسيق dd/mm/yyyy إلى datetime
                final_df["session_date_dt"] = pd.to_datetime(
                    final_df[session_date_col], format="%d/%m/%Y", errors="coerce"
                )

                # التحقق من وجود تواريخ صالحة
                if final_df["session_date_dt"].isna().all():
                    logger.error("❌ جميع التواريخ غير صالحة!")
                    return None

                # إزالة الصفوف التي تحتوي على تواريخ غير صالحة
                final_df = final_df.dropna(subset=["session_date_dt"])

                if final_df.empty:
                    logger.error(
                        "❌ لا توجد بيانات صالحة بعد إزالة التواريخ غير الصالحة"
                    )
                    return None

                date_col = getattr(C, "DATE_COLUMN_NAME", "date")

                # تحويل التواريخ إلى UTC مع معالجة أفضل للأخطاء
                try:
                    final_df[date_col] = (
                        final_df["session_date_dt"]
                        .dt.tz_localize(
                            "Africa/Cairo", ambiguous="NaT", nonexistent="shift_forward"
                        )
                        .dt.tz_convert("UTC")
                    )
                except Exception as tz_error:
                    logger.warning(f"⚠️ خطأ في تحويل المنطقة الزمنية: {tz_error}")
                    # استخدام UTC مباشرة إذا فشل التحويل
                    final_df[date_col] = final_df["session_date_dt"].dt.tz_localize(
                        "UTC"
                    )

                final_df = (
                    final_df.sort_values("session_date_dt", ascending=False)
                    .drop_duplicates(subset=[tenor_col])
                    .sort_values(by=tenor_col)
                )

                logger.info(f"✅ تم معالجة {len(final_df)} سجل بتاريخ صحيح")

                # التحقق النهائي من صحة التواريخ قبل الإرجاع
                if date_col in final_df.columns:
                    invalid_dates = final_df[date_col].dt.year == 1970
                    if invalid_dates.any():
                        logger.error(
                            f"❌ تم العثور على {invalid_dates.sum()} سجل بتاريخ غير صالح (1970)"
                        )
                        # إزالة السجلات ذات التواريخ غير الصالحة
                        final_df = final_df[~invalid_dates]
                        if final_df.empty:
                            logger.error(
                                "❌ لا توجد بيانات صالحة بعد إزالة التواريخ غير الصالحة"
                            )
                            return None
                        logger.info(f"✅ تم الاحتفاظ بـ {len(final_df)} سجل صالح")

            except Exception as e:
                logger.error(f"❌ خطأ في معالجة التواريخ: {e}")
                return None

            return final_df

        except Exception as e:
            logger.error(f"❌ خطأ حرج في تحليل البيانات: {e}", exc_info=True)
            return None

    async def _get_browser_args(self) -> List[str]:
        """الحصول على معاملات المتصفح المناسبة للنظام"""
        base_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
        ]

        if self.is_windows:
            # معاملات إضافية لـ Windows
            base_args.extend(
                [
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-field-trial-config",
                    "--disable-ipc-flooding-protection",
                ]
            )

        return base_args

    @backoff_retry(
        max_retries=3,
        base_delay=5.0,
        max_delay=60.0,
        jitter=True,
        exceptions_to_catch=(Exception,),
        on_retry_callback=lambda retry, delay, ex: logger.warning(
            f"إعادة محاولة الاستخراج {retry} بعد {delay:.1f} ثانية. السبب: {str(ex)}"
        ),
    )
    async def _scrape_from_web_async(self) -> Optional[pd.DataFrame]:
        """استخراج البيانات من موقع البنك المركزي باستخدام Playwright مع دعم محسن لـ Windows"""

        if not PLAYWRIGHT_AVAILABLE:
            logger.error("❌ Playwright غير متوفر")
            return None

        logger.info("🚀 جاري استخراج البيانات من موقع البنك المركزي...")

        browser = None
        context = None
        page = None

        try:
            # إخفاء مخرجات Playwright المزعجة
            with suppress_output():
                async with async_playwright() as p:
                    try:
                        # إعداد المتصفح بخيارات محسنة لـ Windows
                        browser_args = await self._get_browser_args()

                        browser = await p.chromium.launch(
                            headless=True,
                            args=browser_args,
                            timeout=(
                                60000 if self.is_windows else 30000
                            ),  # مهلة أطول على Windows
                        )

                        # إعداد السياق والصفحة
                        user_agent = getattr(
                            C,
                            "USER_AGENT",
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        )

                        context = await browser.new_context(
                            user_agent=user_agent,
                            viewport={"width": 1366, "height": 768},
                            locale="ar-EG",
                        )

                        page = await context.new_page()

                        # تعيين معالجات الأخطاء
                        page.on(
                            "pageerror",
                            lambda err: logger.error(f"خطأ في الصفحة: {err}"),
                        )

                        if logger.isEnabledFor(logging.DEBUG):
                            page.on(
                                "console",
                                lambda msg: logger.debug(
                                    f"رسالة من المتصفح: {msg.text}"
                                ),
                            )

                        # الحصول على URL من المتغيرات
                        cbe_url = getattr(
                            C,
                            "CBE_DATA_URL",
                            "https://www.cbe.org.eg/ar/monetary-policy/treasury-bills-and-bonds",
                        )

                        # الانتقال إلى الصفحة مع معالجة محسنة للمهلة الزمنية
                        timeout_seconds = getattr(C, "SCRAPER_TIMEOUT_SECONDS", 30)
                        if self.is_windows:
                            timeout_seconds = min(
                                timeout_seconds * 2, 60
                            )  # مضاعفة المهلة على Windows

                        logger.info(f"🌐 الانتقال إلى: {cbe_url}")

                        response = await page.goto(
                            cbe_url,
                            timeout=timeout_seconds * 1000,
                            wait_until="networkidle",
                        )

                        # التحقق من حالة الاستجابة
                        if not response or not response.ok:
                            error_msg = f"فشل طلب الصفحة: {response.status if response else 'لا استجابة'}"
                            logger.error(error_msg)
                            raise RuntimeError(error_msg)

                        logger.info(
                            f"✅ تم تحميل الصفحة بنجاح (حالة: {response.status})"
                        )

                        # انتظار تحميل الجداول
                        try:
                            await page.wait_for_selector(
                                "table", timeout=timeout_seconds * 1000, state="visible"
                            )
                            logger.info("✅ تم العثور على الجداول في الصفحة")
                        except Exception as e:
                            logger.warning(f"⚠️ تحذير: لم يتم العثور على جداول: {e}")

                        # إضافة انتظار إضافي للتأكد من تحميل المحتوى
                        await asyncio.sleep(2)

                        # أخذ لقطة شاشة للتوثيق (في وضع التصحيح)
                        if os.environ.get("DEBUG", "").lower() in ["true", "1"]:
                            try:
                                debug_dir = "debug"
                                os.makedirs(debug_dir, exist_ok=True)
                                screenshot_path = os.path.join(
                                    debug_dir,
                                    f"cbe_page_{int(asyncio.get_event_loop().time())}.png",
                                )
                                await page.screenshot(
                                    path=screenshot_path, full_page=True
                                )
                                logger.debug(
                                    f"📸 تم حفظ لقطة شاشة في {screenshot_path}"
                                )
                            except Exception as ss_err:
                                logger.debug(f"⚠️ فشل أخذ لقطة شاشة: {ss_err}")

                        # الحصول على محتوى الصفحة
                        page_source = await page.content()
                        logger.info(
                            f"📄 تم الحصول على محتوى الصفحة ({len(page_source)} حرف)"
                        )

                        # التحقق من هيكل الصفحة وتحليلها
                        self._verify_page_structure(page_source)
                        result = self._parse_cbe_html(page_source)

                        if result is None or result.empty:
                            logger.warning("⚠️ تم الحصول على بيانات فارغة من الصفحة")
                        else:
                            logger.info(f"✅ تم استخراج {len(result)} سجل بنجاح")

                        return result

                    except Exception as e:
                        logger.error(f"❌ فشل استخراج البيانات: {e}", exc_info=True)

                        # معالجة خاصة لأخطاء Playwright
                        error_str = str(e).lower()
                        if (
                            "executable doesn't exist" in error_str
                            or "browser executable" in error_str
                        ):
                            error_msg = (
                                "❌ Playwright browsers not installed. Please run:\n"
                                "playwright install chromium"
                            )
                            logger.error(error_msg)
                            raise RuntimeError(error_msg)

                        if "timeout" in error_str:
                            logger.error(
                                "❌ انتهت مهلة التحميل - تحقق من الاتصال بالإنترنت"
                            )

                        # محاولة التقاط لقطة شاشة للتشخيص
                        if page:
                            try:
                                debug_dir = "debug"
                                os.makedirs(debug_dir, exist_ok=True)
                                screenshot_path = os.path.join(
                                    debug_dir,
                                    f"error_{int(asyncio.get_event_loop().time())}.png",
                                )
                                await page.screenshot(
                                    path=screenshot_path, full_page=True
                                )
                                logger.warning(
                                    f"📸 تم حفظ لقطة شاشة للخطأ في {screenshot_path}"
                                )
                            except Exception as ss_err:
                                logger.debug(f"⚠️ فشل التقاط لقطة شاشة: {ss_err}")

                        raise  # إعادة إثارة الاستثناء للتعامل معه في backoff_retry

        finally:
            # تنظيف الموارد
            try:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception as cleanup_err:
                logger.debug(f"⚠️ خطأ في تنظيف الموارد: {cleanup_err}")

    def _calculate_data_hash(self, df: pd.DataFrame) -> str:
        """حساب تجزئة فريدة للبيانات مع تجاهل التواريخ غير المهمة"""
        try:
            tenor_col = getattr(C, "TENOR_COLUMN_NAME", "tenor")
            yield_col = getattr(C, "YIELD_COLUMN_NAME", "yield")

            # إنشاء نسخة مؤقتة مع إزالة التواريخ المربكة
            temp_df = df[[tenor_col, yield_col]].copy()
            # فرز البيانات للحصول على تجزئة متسقة
            temp_df = temp_df.sort_values(by=tenor_col)
            # حساب التجزئة
            return hashlib.md5(temp_df.to_csv(index=False).encode()).hexdigest()
        except Exception as e:
            logger.error(f"❌ خطأ في حساب التجزئة: {e}")
            return ""

    def _validate_cached_dates(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        التحقق من صحة التواريخ في البيانات المخزنة مؤقتاً وإزالة السجلات غير الصالحة.
        """
        try:
            date_col = getattr(C, "DATE_COLUMN_NAME", "scrape_date")

            if date_col not in df.columns:
                logger.warning(
                    f"⚠️ عمود التاريخ '{date_col}' غير موجود في البيانات المخزنة مؤقتاً"
                )
                logger.info(f"الأعمدة الموجودة: {list(df.columns)}")
                return None

            # تحويل التواريخ إلى datetime للفحص
            date_series = pd.to_datetime(df[date_col], errors="coerce")

            # التحقق من وجود تواريخ غير صالحة (1970-01-01 أو NaT)
            invalid_dates = (date_series.dt.year == 1970) | date_series.isna()

            if invalid_dates.any():
                invalid_count = invalid_dates.sum()
                total_count = len(df)
                logger.warning(
                    f"⚠️ تم العثور على {invalid_count} سجل بتاريخ غير صالح من أصل {total_count} في التخزين المؤقت"
                )

                # إزالة السجلات ذات التواريخ غير الصالحة
                valid_data = df[~invalid_dates].copy()

                if valid_data.empty:
                    logger.error(
                        "❌ لا توجد بيانات صالحة في التخزين المؤقت بعد إزالة التواريخ غير الصالحة"
                    )
                    return None

                logger.info(
                    f"✅ تم الاحتفاظ بـ {len(valid_data)} سجل صالح من التخزين المؤقت"
                )
                return valid_data
            else:
                logger.info(f"✅ جميع التواريخ في التخزين المؤقت صالحة ({len(df)} سجل)")
                return df

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من صحة التواريخ في التخزين المؤقت: {e}")
            return None

    async def get_historical_data_for_gaps(
        self, gaps: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        جلب البيانات التاريخية لملء الفجوات المحددة.
        """
        logger.info(f"🔍 جاري محاولة جلب {len(gaps)} فجوة في البيانات...")

        tenor_col = getattr(C, "TENOR_COLUMN_NAME", "tenor")
        yield_col = getattr(C, "YIELD_COLUMN_NAME", "yield")
        session_date_col = getattr(C, "SESSION_DATE_COLUMN_NAME", "session_date")
        date_col = getattr(C, "DATE_COLUMN_NAME", "date")

        return pd.DataFrame(columns=[tenor_col, yield_col, session_date_col, date_col])

    async def get_latest_yields_async(
        self, force_refresh: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        جلب بيانات أذون الخزانة، مع استخدام التخزين المؤقت لتجنب الطلبات المتكررة.
        """
        cache_key = "df_latest"

        if not force_refresh and self.cache:
            try:
                cached_data = self.cache.get(cache_key)
                if cached_data is not None and not cached_data.empty:
                    logger.info("✅ تم العثور على البيانات في التخزين المؤقت.")

                    # التحقق من صحة التواريخ في البيانات المخزنة مؤقتاً
                    validated_data = self._validate_cached_dates(cached_data)
                    if validated_data is not None and not validated_data.empty:
                        logger.info(
                            f"✅ تم التحقق من صحة {len(validated_data)} سجل من التخزين المؤقت"
                        )
                        return validated_data
                    else:
                        logger.warning(
                            "⚠️ البيانات المخزنة مؤقتاً تحتوي على تواريخ غير صالحة، سيتم إعادة الاستخراج"
                        )
                        # إذا كانت البيانات المخزنة مؤقتاً غير صالحة، احذفها من التخزين المؤقت
                        try:
                            self.cache.invalidate(cache_key)
                            logger.info(
                                "🗑️ تم حذف البيانات غير الصالحة من التخزين المؤقت"
                            )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ خطأ في حذف البيانات غير الصالحة من التخزين المؤقت: {e}"
                            )
            except Exception as e:
                logger.warning(f"⚠️ خطأ في قراءة التخزين المؤقت: {e}")

        if force_refresh:
            logger.info("🔄 تم تفعيل خيار التحديث القسري، يتم تجاوز التخزين المؤقت.")

        live_data = await self._scrape_from_web_async()

        if live_data is not None and not live_data.empty and self.cache:
            try:
                self.cache.set(cache_key, live_data)
                logger.info("💾 تم تخزين البيانات الجديدة في التخزين المؤقت.")
            except Exception as e:
                logger.warning(f"⚠️ خطأ في كتابة التخزين المؤقت: {e}")

        return live_data

    def get_latest_yields(self) -> Optional[pd.DataFrame]:
        """نسخة متزامنة من get_latest_yields_async"""
        try:
            if self.is_windows:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    return asyncio.create_task(self.get_latest_yields_async()).result()
                else:
                    return asyncio.run(self.get_latest_yields_async())
            else:
                return asyncio.run(self.get_latest_yields_async())
        except Exception as e:
            logger.error(f"❌ خطأ في get_latest_yields: {e}")
            return None


async def fetch_and_update_data_async(
    data_source: CbeScraper,
    data_store: HistoricalDataStore,
    status_callback: Optional[Callable[[str], None]] = None,
    force_refresh: bool = False,
) -> Optional[bool]:
    """
    جلب البيانات وتحديث قاعدة البيانات مع مقارنة دقيقة لتجنب التحديثات غير الضرورية.
    """
    try:
        if status_callback:
            status_callback("جاري جلب البيانات...")

        # الخطوة 1: جلب البيانات من الموقع، مع تجاهل الكاش إذا طُلب ذلك
        latest_data = await data_source.get_latest_yields_async(
            force_refresh=force_refresh
        )

        if latest_data is None or latest_data.empty:
            if status_callback:
                status_callback("لم يتم العثور على بيانات جديدة على الموقع")
            _increment_failure_count()
            return False

        if status_callback:
            status_callback("تم الجلب، جاري التحقق من التكرار...")

        # التحقق دائمًا مما إذا كانت البيانات مكررة قبل أي محاولة ملء فجوات أو حفظ
        debug_cols = [
            getattr(C, "TENOR_COLUMN_NAME", "tenor"),
            getattr(C, "YIELD_COLUMN_NAME", "yield"),
            getattr(C, "SESSION_DATE_COLUMN_NAME", "session_date"),
        ]
        logger.info(
            f"[DEBUG] قيم الأعمدة الأساسية في latest_data:\n{latest_data[debug_cols].to_string(index=False)}"
        )
        is_duplicate, reason = data_store.is_duplicate_data(latest_data)
        if is_duplicate:
            if status_callback:
                status_callback(f"✅ البيانات مكررة - لا حاجة للحفظ: {reason}")
            logger.info(f"✅ تم اكتشاف البيانات المكررة: {reason}")
            return False

        # إذا لم تكن مكررة، تحقق من الفجوات أولاً
        try:
            gaps = data_store.detect_data_gaps()
            if gaps:
                if status_callback:
                    status_callback(
                        f"تم اكتشاف {len(gaps)} فجوة في البيانات، جاري المحاولة لملءها..."
                    )
                historical_data = await data_source.get_historical_data_for_gaps(gaps)
                if not historical_data.empty:
                    data_store.save_data(historical_data)
                    if status_callback:
                        status_callback(
                            f"✅ تم ملء {len(historical_data)} سجل لفجوات البيانات"
                        )
        except Exception as e:
            logger.warning(f"⚠️ خطأ في معالجة فجوات البيانات: {e}")

        # الآن نقوم بالحفظ لأن البيانات جديدة وغير مكررة
        try:
            if status_callback:
                status_callback("جاري حفظ البيانات الجديدة...")
            data_store.save_data(latest_data)

            if status_callback:
                status_callback("✅ تم حفظ البيانات الجديدة بنجاح!")

            logger.info("✅ تم حفظ البيانات الجديدة في قاعدة البيانات")
            _reset_failure_count()
            return True

        except Exception as e:
            logger.error(f"❌ خطأ في حفظ البيانات: {e}")
            if status_callback:
                status_callback(f"فشل حفظ البيانات: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"❌ خطأ عام في fetch_and_update_data_async: {e}", exc_info=True)
        if status_callback:
            status_callback(f"خطأ في العملية: {str(e)}")
        return None


# دوال مساعدة لحساب عدد مرات الفشل
_FAILURE_COUNT = 0
_MAX_FAILURES = 5


def _increment_failure_count() -> int:
    """زيادة عداد الفشل وترجيع القيمة الحالية"""
    global _FAILURE_COUNT
    _FAILURE_COUNT += 1
    logger.warning(
        f"⚠️ فشل في جلب البيانات (المحاولة {_FAILURE_COUNT}/{_MAX_FAILURES})"
    )
    return _FAILURE_COUNT


def _reset_failure_count():
    """إعادة تعيين عداد الفشل"""
    global _FAILURE_COUNT
    _FAILURE_COUNT = 0
    logger.info("🔄 تم إعادة تعيين عداد الفشل بعد التحديث الناجح")


def fetch_and_update_data(
    data_source: YieldDataSource,
    data_store: HistoricalDataStore,
    status_callback: Optional[Callable[[str], None]] = None,
    force_refresh: bool = False,
) -> Optional[bool]:
    """نسخة متزامنة من fetch_and_update_data_async مع دعم محسن لـ Windows"""
    try:
        return asyncio.run(
            fetch_and_update_data_async(
                data_source, data_store, status_callback, force_refresh
            )
        )
    except RuntimeError as e:
        if "cannot run current event loop" in str(e):
            loop = asyncio.get_running_loop()
            _task = loop.create_task(
                fetch_and_update_data_async(
                    data_source, data_store, status_callback, force_refresh
                )
            )
            logger.warning("Called fetch_and_update_data from a running event loop.")
            return None
        else:
            raise

    except Exception as e:
        logger.error(f"❌ خطأ في fetch_and_update_data: {e}", exc_info=True)
        if status_callback:
            status_callback(f"خطأ في العملية: {str(e)}")
        return None
