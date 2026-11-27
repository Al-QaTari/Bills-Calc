"""
Constants for the Treasury Bills Calculator application.
الثوابت المستخدمة في تطبيق حاسبة أذون الخزانة.

This file consolidates all magic strings, column names, URLs, and default values
to improve maintainability and prevent errors.
"""

# =============================================================================
# COLUMN NAMES - أسماء الأعمدة
# =============================================================================
TENOR_COLUMN_NAME = "tenor"
YIELD_COLUMN_NAME = "yield"
DATE_COLUMN_NAME = "scrape_date"
SESSION_DATE_COLUMN_NAME = "session_date"

# =============================================================================
# DATABASE - قاعدة البيانات
# =============================================================================
DB_FILENAME = "cbe_historical_data.db"
TABLE_NAME = "cbe_t_bills"

# =============================================================================
# WEB SCRAPING - استخراج البيانات من الويب
# =============================================================================
CBE_DATA_URL = "https://www.cbe.org.eg/ar/auctions/egp-t-bills"
YIELD_ANCHOR_TEXT = "متوسط العائد المرجح"
ACCEPTED_BIDS_KEYWORD = "المقبولة"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Web scraping controls
SCRAPER_RETRIES = 3
SCRAPER_RETRY_DELAY_SECONDS = 10
SCRAPER_TIMEOUT_SECONDS = 60

# =============================================================================
# FINANCIAL - المالية
# =============================================================================
DAYS_IN_YEAR = 365.0
DEFAULT_TAX_RATE_PERCENT = 20.0
MIN_T_BILL_AMOUNT = 25000.0
T_BILL_AMOUNT_STEP = 25000.0

# =============================================================================
# TENORS - الآجال المتاحة
# =============================================================================
# الآجال الأساسية. أذن السنة بيظهر أحيانًا 357 أو 336 بدل 364 (حسب تاريخ الإصدار)،
# وبيتوحد تلقائيًا في tenors.py. الآجال الجديدة بتظهر تلقائيًا من البيانات.
TENORS = [91, 182, 273, 364]

# =============================================================================
# LOCALIZATION - التوطين
# =============================================================================
TIMEZONE = "Africa/Cairo"

# =============================================================================
# INITIAL DATA (FALLBACK) - البيانات الأولية (الاحتياطية)
# =============================================================================
INITIAL_DATA = {
    TENOR_COLUMN_NAME: [91, 182, 273, 364],
    YIELD_COLUMN_NAME: [26.0, 26.5, 27.0, 27.5],
    SESSION_DATE_COLUMN_NAME: ["N/A", "N/A", "N/A", "N/A"],
}

# =============================================================================
# UI CONSTANTS - ثوابت واجهة المستخدم
# =============================================================================
APP_TITLE = "حاسبة أذون الخزانة المصرية"
APP_HEADER = "تطبيق تفاعلي لحساب وتحليل عوائد أذون الخزانة المصرية"
PRIMARY_CALCULATOR_TITLE = "🧮 حاسبة العائد الأساسية (الشراء والاحتفاظ)"
SECONDARY_CALCULATOR_TITLE = "⚖️ حاسبة تحليل البيع في السوق الثانوي"
HELP_TITLE = "💡 شرح ومساعدة (أسئلة شائعة)"
AUTHOR_NAME = "Mohamed AL-QaTri"

# =============================================================================
# PATHS - المسارات
# =============================================================================
CSS_FILE_PATH = "css/styles.css"

# =============================================================================
# ESSENTIAL TEXT MARKERS - علامات النصوص الأساسية
# =============================================================================
# List of essential texts that must be present on the page to ensure code functionality
ESSENTIAL_TEXT_MARKERS = [
    "النتائج",
    "تاريخ الجلسة",
    YIELD_ANCHOR_TEXT,  # "متوسط العائد المرجح"
    ACCEPTED_BIDS_KEYWORD,  # "المقبولة"
]

# =============================================================================
# LEDGER - دفتر المحفظة (رسوم تقديرية، ملاحظة في صفحة المساعدة)
# القيم دي تقدير لحد ما تتأكد من كشف الحساب، ومش أرقام رسمية مؤكدة.
# =============================================================================
LEDGER_TABLE_NAME = "tbill_purchases"
LEDGER_REDEMPTION_FEE_RATE = 0.001  # 1 في الألف
LEDGER_REDEMPTION_FEE_CAP = 1000.0
LEDGER_CUSTODY_ANNUAL_RATE = 0.0002  # 0.02% سنويًا
LEDGER_SESSION_TIMEOUT_SECONDS = 900
LEDGER_MAX_LOGIN_ATTEMPTS = 5
LEDGER_GLOBAL_MAX_FAILS = 20  # محاولات غلط من كل الجلسات معًا في 10 دقايق قبل القفل
LEDGER_DB_CONNECT_TIMEOUT = 5
LEDGER_DB_POOL_TIMEOUT = 8
LEDGER_DB_STATEMENT_TIMEOUT_MS = 8000
LEDGER_TIMELINE_MAX_OPEN = 80
LEDGER_TIMELINE_MAX_CLOSED = 20
LEDGER_TABLE_MAX_ROWS = 300
LEDGER_PURCHASE_FEE_RATE = 0.000025  # 2.5 لكل 100 ألف
LEDGER_PURCHASE_FEE_CAP = 1000.0
LEDGER_NEAR_MATURITY_DAYS = 14  # أقل من كده الأذن يتلوّن "قرب يستحق" في الخط الزمني
