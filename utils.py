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


LIGHT_THEME_ATTR = "data-app-theme"

# يقرأ لون خلفية Streamlit الفعلي (مش إعداد الجهاز) ويكتب data-app-theme على <html>.
# السبب: st.context.theme.type وإعداد الجهاز ممكن يختلفوا عن الثيم اللي Streamlit
# بيرسمه فعلاً (مثلاً لو المستخدم اختار Light من Settings والجهاز Dark)، وده كان
# بيخلط ألوان فاتحة وغامقة.
_THEME_SYNC_JS = """
(function () {
  if (window.__bcThemeSync) { window.__bcThemeSync(); return; }
  function apply() {
    var app = document.querySelector('.stApp');
    if (!app) { return; }
    var m = getComputedStyle(app).backgroundColor.match(/[\\d.]+/g);
    if (!m) { return; }
    var lum = 0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2];
    document.documentElement.setAttribute('data-app-theme', lum > 140 ? 'light' : 'dark');
  }
  window.__bcThemeSync = apply;
  apply();
  var obs = new MutationObserver(apply);
  obs.observe(document.documentElement, {attributes: true, attributeFilter: ['class', 'style']});
  var app = document.querySelector('.stApp');
  if (app) { obs.observe(app, {attributes: true, attributeFilter: ['class', 'style']}); }
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { setTimeout(apply, 50); });
  }
  setInterval(apply, 1000);
})();
"""


def scope_css_to_light_theme(css: str) -> str:
    """
    Prefix every rule in a simple stylesheet (no @media / @keyframes blocks) with
    html[data-app-theme="light"], so the rules only apply when the page is really light.
    ':root' becomes the html element itself.
    """
    import re

    prefix = f'html[{LIGHT_THEME_ATTR}="light"]'
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = block.group(1).strip(), block.group(2)
        if not selectors or selectors.startswith("@"):
            continue
        scoped = []
        for sel in selectors.split(","):
            sel = sel.strip()
            if not sel:
                continue
            if sel == ":root":
                scoped.append(prefix)
            else:
                scoped.append(f"{prefix} {sel}")
        out.append(f"{', '.join(scoped)} {{{body}}}")
    return "\n".join(out)


def load_light_theme_css(css_dir: str) -> None:
    """
    Inject css/light.css scoped to html[data-app-theme="light"].

    Dark stays the base look from styles.css. The attribute is set in the browser
    from the real Streamlit background color, so the light rules apply exactly when
    the page is light, whatever the device setting or st.context.theme says.
    """
    light_path = os.path.join(css_dir, "light.css")
    if not os.path.exists(light_path):
        logger.warning(f"Light theme CSS not found at path: {light_path}")
        return
    with open(light_path, encoding="utf-8") as f:
        css = scope_css_to_light_theme(f.read())
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    st.html(f"<script>{_THEME_SYNC_JS}</script>", unsafe_allow_javascript=True)


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
    for tenor in sorted(df_data[C.TENOR_COLUMN_NAME].unique()):
        tenor_data = df_data[df_data[C.TENOR_COLUMN_NAME] == tenor]
        if not tenor_data.empty:
            yield_rate = tenor_data[C.YIELD_COLUMN_NAME].iloc[0]
            tenor_yield_map[tenor] = yield_rate
            StateManager.set(f"latest_yield_{tenor}", yield_rate)

    # الآجال الحالية للحاسبات (من البيانات نفسها)
    st.session_state["_df_data_for_tenors"] = df_data.copy()
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
