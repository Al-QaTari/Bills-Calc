"""
Utility functions for the Treasury Bills Calculator application.
وظائف مساعدة لتطبيق حاسبة أذون الخزانة.
"""

import os
import logging
from typing import Optional
import streamlit as st
from state_manager import StateManager
import constants as C

logger = logging.getLogger(__name__)


def prepare_arabic_text(text: str) -> str:
    """
    Prepare Arabic text for display.

    Args:
        text: The text to prepare

    Returns:
        Prepared text string
    """
    try:
        return str(text)
    except Exception:
        logger.error(f"Could not convert text to string: {text}", exc_info=True)
        return ""


def load_css(file_path: str) -> None:
    """
    Load CSS file and inject it into Streamlit.

    Args:
        file_path: Path to the CSS file
    """
    if os.path.exists(file_path):
        logger.debug(f"Loading CSS from {file_path}")
        with open(file_path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        logger.warning(f"CSS file not found at path: {file_path}")


def get_streamlit_theme_type() -> Optional[str]:
    """Return "light" or "dark" from the active Streamlit theme, or None if unknown."""
    try:
        theme_type = st.context.theme.type
    except Exception:
        return None
    return theme_type if theme_type in ("light", "dark") else None


def load_light_theme_css(css_dir: str) -> None:
    """
    Inject css/light.css when the Streamlit theme is light.

    Dark stays the base look from styles.css. If the theme cannot be detected,
    the light rules are wrapped in a prefers-color-scheme media query so they
    still follow the device setting.
    """
    theme_type = get_streamlit_theme_type()
    if theme_type == "dark":
        return
    light_path = os.path.join(css_dir, "light.css")
    if not os.path.exists(light_path):
        logger.warning(f"Light theme CSS not found at path: {light_path}")
        return
    with open(light_path, encoding="utf-8") as f:
        css = f.read()
    if theme_type is None:
        css = f"@media (prefers-color-scheme: light) {{{css}}}"
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def load_polish_css(css_dir: str) -> None:
    """Inject css/polish.css (rounded corners, hover/click motion, glow, emoji font)."""
    polish_path = os.path.join(css_dir, "polish.css")
    if not os.path.exists(polish_path):
        logger.warning(f"Polish CSS not found at path: {polish_path}")
        return
    with open(polish_path, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def setup_logging(level: int = logging.INFO) -> None:
    """
    Setup logging configuration.

    Args:
        level: Logging level
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.StreamHandler()],
        )
        logger.info("Logging configured successfully.")


def format_currency(value: Optional[float], currency_symbol: str = "جنيه") -> str:
    """
    Format a numeric value as currency.

    Args:
        value: The numeric value to format
        currency_symbol: Currency symbol to append

    Returns:
        Formatted currency string
    """
    if value is None:
        logger.debug("Formatting a None value to default currency string.")
        return f"- {prepare_arabic_text(currency_symbol)}"

    try:
        sign = "-" if value < 0 else ""
        return f"{sign}{abs(value):,.2f} {prepare_arabic_text(currency_symbol)}"
    except (ValueError, TypeError):
        logger.error(f"Could not format value '{value}' as currency.", exc_info=True)
        return str(value)


def connect_auction_data_with_calculators() -> None:
    """
    Connect auction data with calculators for direct value usage.
    ربط بيانات العطاءات بالحاسبات للاستخدام المباشر للقيم.
    """
    # Ensure data exists before attempting connection
    if not StateManager.has("df_data"):
        logger.warning("لا توجد بيانات متاحة لربطها بالحاسبات")
        return

    df_data = StateManager.get("df_data")

    if df_data is None or df_data.empty:
        logger.warning("بيانات العطاءات فارغة، لا يمكن الربط")
        return

    # Store yield rates for each tenor in session state for direct use
    tenor_yield_map = {}

    # Extract yield rates for each tenor
    for tenor in C.TENORS:
        tenor_data = df_data[df_data[C.TENOR_COLUMN_NAME] == tenor]
        if not tenor_data.empty:
            yield_rate = tenor_data[C.YIELD_COLUMN_NAME].iloc[0]
            tenor_yield_map[tenor] = yield_rate
            StateManager.set(f"latest_yield_{tenor}", yield_rate)

    # Store complete map for quick access
    StateManager.set("tenor_yield_map", tenor_yield_map)
    logger.info(f"تم ربط بيانات العائد: {tenor_yield_map}")


def get_yield_for_tenor(tenor: int) -> Optional[float]:
    """
    Get current yield rate for a specific tenor.

    Args:
        tenor: The tenor in days

    Returns:
        Current yield rate or None if not available
    """
    return StateManager.get(f"latest_yield_{tenor}")


def use_latest_auction_data(tenor: int) -> float:
    """
    Use latest auction data to set yield rate in calculators.

    Args:
        tenor: The tenor in days

    Returns:
        Yield rate to use (default if not available)
    """
    default_yield = 25.0  # Default yield if data not available

    yield_rate = get_yield_for_tenor(tenor)
    if yield_rate is not None:
        return yield_rate

    # Try to connect data again if not available
    connect_auction_data_with_calculators()

    # Second attempt to get data after connection
    yield_rate = get_yield_for_tenor(tenor)
    return yield_rate if yield_rate is not None else default_yield


def render_date_cards(purchase_date: str, sale_date: str, maturity_date: str) -> None:
    """
    Render date cards in a centered layout.
    عرض بطاقات التواريخ في تخطيط متمركز.

    Args:
        purchase_date: Purchase date string
        sale_date: Sale date string
        maturity_date: Maturity date string
    """
    date_cards_html = f"""
    <div class="date-cards-container">
        <div class="date-card">
            <div class="date-card-icon">📅</div>
            <div class="date-card-label">تاريخ الشراء</div>
            <div class="date-card-value">{prepare_arabic_text(purchase_date)}</div>
        </div>
        <div class="date-card">
            <div class="date-card-icon">💰</div>
            <div class="date-card-label">تاريخ البيع</div>
            <div class="date-card-value">{prepare_arabic_text(sale_date)}</div>
        </div>
        <div class="date-card">
            <div class="date-card-icon">🎯</div>
            <div class="date-card-label">تاريخ الاستحقاق</div>
            <div class="date-card-value">{prepare_arabic_text(maturity_date)}</div>
        </div>
    </div>
    """
    st.markdown(date_cards_html, unsafe_allow_html=True)


def validate_face_value(value) -> Optional[str]:
    """Return an Arabic error message if value is not a valid T-bill amount.

    A valid amount is at least C.MIN_T_BILL_AMOUNT and an exact multiple of
    C.T_BILL_AMOUNT_STEP (25,000 EGP). Returns None when the amount is valid.
    """
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(str(value))
        step = Decimal(str(C.T_BILL_AMOUNT_STEP))
        minimum = Decimal(str(C.MIN_T_BILL_AMOUNT))
    except (InvalidOperation, TypeError, ValueError):
        return "القيمة الاسمية غير صحيحة."
    if not amount.is_finite():
        return "القيمة الاسمية غير صحيحة."
    if amount < minimum:
        return f"أقل قيمة اسمية هي {int(minimum):,} جنيه."
    if amount % step != 0:
        return f"القيمة الاسمية لازم تكون من مضاعفات {int(step):,} جنيه (مثل 25,000 أو 50,000 أو 75,000)."
    return None
