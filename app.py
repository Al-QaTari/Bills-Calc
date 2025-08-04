"""
Treasury Bills Calculator - Main Application
حاسبة أذون الخزانة - التطبيق الرئيسي

This module contains the main Streamlit application for calculating
treasury bills yields and secondary market values.
"""

import os
import logging
import streamlit as st
import sentry_sdk
from dotenv import load_dotenv
import subprocess

from dependency_container import container
from utils import (
    setup_logging,
    prepare_arabic_text,
    load_css,
    StateManager,
)
from treasury_core.ports import HistoricalDataStore, YieldDataSource
from ui.home_page import render_home_page
from ui.primary_yield_calculator import render_primary_yield_calculator
from ui.secondary_sale_calculator import render_secondary_sale_calculator
from ui.historical_data_view import render_historical_data_view
from ui.help_page import render_help_page
from secret_admin_panel import render_secret_admin_panel
from error_handler import suppress_websocket_errors

# Load environment variables
load_dotenv()

# Initialize error suppression
suppress_websocket_errors()

# Initialize logging with better error handling
setup_logging(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

# Error suppression is now handled in error_handler.py

# Initialize Sentry for error tracking
sentry_dsn = os.environ.get("SENTRY_DSN")
sentry_env = os.environ.get("SENTRY_ENVIRONMENT", "production")  # 👈 قيمة افتراضية

if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
        environment=sentry_env,
    )


def ensure_playwright_browsers_installed():
    """Ensure Playwright browsers are installed for web scraping."""
    try:
        import os

        # Check if we're on Windows and handle accordingly
        if os.name == "nt":  # Windows
            logging.info("🪟 Windows detected, using alternative Playwright setup")
            return _ensure_playwright_windows()
        else:
            return _ensure_playwright_unix()

    except Exception as e:
        logging.error(f"❌ Error ensuring Playwright browsers: {str(e)}")
        return False


def _ensure_playwright_windows():
    """Windows-specific Playwright browser installation."""
    try:
        import sys

        # Try to install browsers directly without checking first
        logging.info("🔧 Installing Playwright browsers on Windows...")

        # Use python -m playwright install to avoid subprocess issues
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
            shell=True,  # Use shell on Windows
        )

        if result.returncode == 0:
            logging.info("✅ Playwright browsers installed successfully on Windows")
            return True
        else:
            logging.warning(f"⚠️ Playwright installation warning: {result.stderr}")
            # Don't fail completely, just warn
            return True

    except Exception as e:
        logging.warning(f"⚠️ Playwright setup warning on Windows: {str(e)}")
        return True  # Continue anyway


def _ensure_playwright_unix():
    """Unix-specific Playwright browser installation."""
    try:
        from playwright.sync_api import sync_playwright

        # Check if browsers are installed
        with sync_playwright() as p:
            try:
                # Try to launch browser to check if it's installed
                browser = p.chromium.launch(headless=True)
                browser.close()
                logging.info("✅ Playwright browsers are already installed")
                return True
            except Exception as e:
                logging.warning(f"Playwright browsers not found: {str(e)}")

        # Install browsers if not found
        logging.info("🔧 Installing Playwright browsers...")
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            logging.info("✅ Playwright browsers installed successfully")
            return True
        else:
            logging.error(f"❌ Failed to install Playwright browsers: {result.stderr}")
            return False

    except ImportError:
        logging.warning("⚠️ Playwright not installed, skipping browser installation")
        return False
    except Exception as e:
        logging.error(f"❌ Error ensuring Playwright browsers: {str(e)}")
        return False


@st.cache_resource
def get_db_manager() -> HistoricalDataStore:
    """Get cached database manager instance."""
    return container.get(HistoricalDataStore)


@st.cache_resource
def get_data_source() -> YieldDataSource:
    """Get cached data source instance."""
    return container.get(YieldDataSource)


def load_historical_data():
    """Load historical data into session state."""
    if "historical_df" not in st.session_state:
        db_manager = get_db_manager()
        historical_data = db_manager.load_all_historical_data()
        StateManager.set("historical_df", historical_data)
        logging.info(f"تم تحميل {len(historical_data)} سجل تاريخي في ذاكرة التطبيق.")

        # إضافة معلومات تشخيصية
        if not historical_data.empty:
            logging.info(
                f"نطاق التواريخ: من {historical_data['scrape_date'].min()} إلى {historical_data['scrape_date'].max()}"
            )
            logging.info(f"الآجال المتاحة: {sorted(historical_data['tenor'].unique())}")


def render_section_header(icon: str, title: str, subtitle: str):
    """Render a section header with icon, title, and subtitle."""
    st.markdown(
        f"""
        <div class="section-header">
            <div class="section-icon">{icon}</div>
            <h2 class="section-title">{prepare_arabic_text(title)}</h2>
            <p class="section-subtitle">{prepare_arabic_text(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_divider():
    """Render a decorative section divider."""
    section_divider = """
    <div class="section-divider">
        <div class="divider-line"></div>
        <div class="divider-icon">✦</div>
        <div class="divider-line"></div>
    </div>
    """
    st.markdown(section_divider, unsafe_allow_html=True)


def main():
    """Main application function."""
    try:
        # Configure page
        st.set_page_config(
            layout="wide",
            page_title=prepare_arabic_text("حاسبة أذون الخزانة"),
            page_icon="🏦",
        )
    except Exception as e:
        logging.warning(f"Page config error (non-critical): {str(e)}")
        # Continue without page config if it fails

    # Ensure Playwright browsers are installed
    try:
        ensure_playwright_browsers_installed()
    except Exception as e:
        logging.warning(f"Playwright browser installation warning: {str(e)}")
        # Continue without Playwright if installation fails

    # Load CSS styles
    try:
        # Load main styles
        css_path = os.path.join(os.path.dirname(__file__), "css", "styles.css")
        if os.path.exists(css_path):
            load_css(css_path)
        else:
            st.warning("styles.css not found.")
    except Exception as e:
        logging.error(f"Error loading CSS files: {str(e)}")

    # Load historical data
    try:
        load_historical_data()
    except Exception as e:
        logging.error(f"Error loading historical data: {str(e)}")
        st.error("حدث خطأ في تحميل البيانات التاريخية")

    # Render Home Page
    render_home_page()
    render_section_divider()

    # Render Primary Yield Calculator
    render_section(
        "🧮",
        "حاسبة العائد الأساسية",
        "حساب العائد على استثمارك في أذون الخزانة",
        render_primary_yield_calculator,
    )
    render_section_divider()

    # Render Secondary Sale Calculator
    render_section(
        "⚖️",
        "حاسبة البيع الثانوي",
        "حساب قيمة البيع في السوق الثانوي قبل تاريخ الاستحقاق",
        render_secondary_sale_calculator,
    )
    render_section_divider()

    # Render Historical Data
    render_section(
        "📈",
        "البيانات التاريخية",
        "تتبع أسعار العائد السابقة وتحليل اتجاهات السوق",
        render_historical_data_view,
    )
    render_section_divider()

    # Render Help Page
    render_section(
        "💡",
        "المساعدة والإرشادات",
        "الأسئلة الشائعة وكيفية استخدام التطبيق",
        render_help_page,
    )
    try:
        render_secret_admin_panel(get_db_manager())
    except Exception as e:
        logging.error(f"Error rendering secret admin panel: {str(e)}")
    # لا نريد إظهار خطأ للمستخدم العادي، فقط التسجيل


def render_section(header_icon, header_title, header_subtitle, render_function):
    """Renders a section with error handling."""
    try:
        render_section_header(header_icon, header_title, header_subtitle)
        render_function()
    except Exception as e:
        logging.error(f"Error rendering {header_title}: {str(e)}")
        st.error(f"حدث خطأ في {header_title}")


if __name__ == "__main__":
    main()
