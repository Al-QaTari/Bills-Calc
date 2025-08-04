"""
Home page component for the Treasury Bills Calculator application.
مكون الصفحة الرئيسية لتطبيق حاسبة أذون الخزانة.

This module contains the home page functionality including:
- Display of latest auction data
- Countdown to next auction
- Data update functionality
- Auction results display
"""

import streamlit as st
import pandas as pd
import pytz
from datetime import datetime, timedelta
from utils import prepare_arabic_text, StateManager
from dependency_container import container
from treasury_core.ports import HistoricalDataStore
import constants as C
import subprocess
import sys
from pathlib import Path


def update_data_async(force_refresh: bool = False, is_force_update: bool = False):
    """
    Run data update script asynchronously.
    تشغيل سكريبت تحديث البيانات بشكل غير متزامن.

    Args:
        force_refresh: Whether to force refresh and bypass cache
        is_force_update: Whether this is a force update button click
    """
    st.session_state.update_status = "updating"

    if is_force_update:
        st.session_state.update_message = "🚀 جاري التحديث الشامل من قاعدة البيانات..."
    else:
        st.session_state.update_message = "🔄 جاري التحديث السريع من قاعدة البيانات..."

    try:
        base_dir = Path(__file__).resolve().parent.parent
        update_script = str(base_dir / "update_data.py")

        # Prepare command with force refresh flag if needed
        cmd = [sys.executable, update_script]
        if force_refresh:
            cmd.append("--force-refresh")

        # Run script and capture output
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,  # 60 seconds timeout
        )

        if result.returncode == 0:
            st.session_state.update_status = "success"
            if is_force_update:
                st.session_state.update_message = "✅ تم التحديث الشامل بنجاح - تم تحديث البيانات من قاعدة البيانات PostgreSQL"
            else:
                st.session_state.update_message = (
                    "✅ تم التحديث السريع بنجاح - تم تحديث البيانات من قاعدة البيانات"
                )
        else:
            st.session_state.update_status = "failed"
            error_msg = result.stderr if result.stderr else "خطأ غير معروف"
            if is_force_update:
                st.session_state.update_message = f"❌ فشل في التحديث الشامل من قاعدة البيانات PostgreSQL\n\nتفاصيل الخطأ:\n{error_msg}"
            else:
                st.session_state.update_message = f"❌ فشل في التحديث السريع من قاعدة البيانات\n\nتفاصيل الخطأ:\n{error_msg}"

    except subprocess.TimeoutExpired:
        st.session_state.update_status = "failed"
        if is_force_update:
            st.session_state.update_message = (
                "⏰ انتهت مهلة التحديث الشامل من قاعدة البيانات PostgreSQL"
            )
        else:
            st.session_state.update_message = (
                "⏰ انتهت مهلة التحديث السريع من قاعدة البيانات"
            )
    except Exception as e:
        st.session_state.update_status = "failed"
        error_details = str(e)
        if is_force_update:
            st.session_state.update_message = f"❌ فشل في التحديث الشامل من قاعدة البيانات PostgreSQL\n\nتفاصيل الخطأ:\n{error_details}"
        else:
            st.session_state.update_message = f"❌ فشل في التحديث السريع من قاعدة البيانات\n\nتفاصيل الخطأ:\n{error_details}"


def get_next_auction_date(today: datetime) -> tuple:
    """
    Calculate the next auction date.
    حساب تاريخ العطاء القادم.

    Args:
        today: Current date

    Returns:
        Tuple of (next_auction_date, day_name)
    """
    days_to_thursday = (3 - today.weekday() + 7) % 7
    days_to_sunday = (6 - today.weekday() + 7) % 7
    next_thursday = today + timedelta(days=days_to_thursday)
    next_sunday = today + timedelta(days=days_to_sunday)
    return (
        (next_thursday, "الخميس")
        if next_thursday.date() < next_sunday.date()
        else (next_sunday, "الأحد")
    )


def format_countdown(time_delta: timedelta) -> str:
    """
    Format countdown time in Arabic.
    تنسيق الوقت المتبقي باللغة العربية.

    Args:
        time_delta: Time difference

    Returns:
        Formatted countdown string
    """
    parts = []
    days = time_delta.days
    hours = time_delta.seconds // 3600
    minutes = (time_delta.seconds % 3600) // 60
    if days > 0:
        parts.append(f"{days} يوم")
    if hours > 0:
        parts.append(f"{hours} ساعة")
    if minutes > 0 and not parts:
        parts.append(f"{minutes} دقيقة")
    return " و ".join(parts) if parts else "قريباً جداً"


def display_auction_results(
    title: str, info: str, df: pd.DataFrame, expected_tenors: list
):
    """
    Display auction results in a formatted way.
    عرض نتائج العطاء بتنسيق منظم.

    Args:
        title: Title for the auction results
        info: Information about the auction
        df: DataFrame containing auction data
        expected_tenors: List of expected tenors
    """
    session_date_str = prepare_arabic_text("تاريخ غير محدد")
    filtered_df = pd.DataFrame()
    if not df.empty and C.TENOR_COLUMN_NAME in df.columns:
        filtered_df = df[df[C.TENOR_COLUMN_NAME].isin(expected_tenors)]
        if not filtered_df.empty:
            session_date_str = str(filtered_df[C.SESSION_DATE_COLUMN_NAME].iloc[0])

    st.markdown(
        f'<div class="auction-title-container"><span class="auction-title-span">📊 {prepare_arabic_text(f"{title} - {session_date_str}")}</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="auction-info-container">🗓️ {prepare_arabic_text(info)}<span class="auction-info-note">للشراء يتطلب التواجد في البنك قبل الساعة 10 صباحًا في يوم العطاء.</span></div>',
        unsafe_allow_html=True,
    )

    tenor_style_map = {
        91: ("yellow", "🟡"),
        182: ("blue", "🔵"),
        273: ("purple", "🟣"),
        364: ("white", "⚪️"),
    }
    # A default map for any other tenors that might be added
    default_color_map = {
        0: ("default", "🟢"),
        1: ("blue", "🔵"),
        2: ("green", "🟡"),
        3: ("purple", "🟣"),
    }

    tenor_cards_html = "<div class='tenor-cards-container'>"
    for i, tenor in enumerate(expected_tenors):
        label = prepare_arabic_text(f"أجل {tenor} يوم")
        tenor_data = (
            filtered_df[filtered_df[C.TENOR_COLUMN_NAME] == tenor]
            if not filtered_df.empty
            else pd.DataFrame()
        )
        value = (
            f"{tenor_data[C.YIELD_COLUMN_NAME].iloc[0]:.3f}%"
            if not tenor_data.empty
            else prepare_arabic_text("غير متاح")
        )

        if tenor in tenor_style_map:
            color_name, icon = tenor_style_map[tenor]
        else:
            color_name, icon = default_color_map.get(
                i % len(default_color_map), ("default", "🟢")
            )

        tenor_cards_html += (
            f"<div class='tenor-card tenor-card--{color_name}'>"
            f"<div class='tenor-card-icon'>{icon}</div>"
            f"<div class='tenor-card-label'>{label}</div>"
            f"<div class='tenor-card-value'>{value}</div>"
            f"</div>"
        )
    tenor_cards_html += "</div>"
    st.markdown(tenor_cards_html, unsafe_allow_html=True)


def render_home_page():
    """
    Render the home page with latest data and upcoming auctions.
    عرض الصفحة الرئيسية مع أحدث البيانات والعطاءات القادمة.
    """
    # Load data from database
    db_adapter = container.get(HistoricalDataStore)
    data_df, last_update = db_adapter.load_latest_data()
    StateManager.set("df_data", data_df)
    last_update_date, last_update_time = (
        last_update if last_update else ("البيانات الأولية", None)
    )

    # Parse last update date
    last_update_dt = None
    try:
        if last_update_date and last_update_date != "البيانات الأولية":
            last_update_dt = datetime.strptime(last_update_date, "%Y-%m-%d")
    except Exception:
        pass

    # Calculate next auction date
    now_cairo = datetime.now(pytz.timezone(C.TIMEZONE))
    # تعريف المتغيرين قبل استخدامهما
    next_auction_dt, next_auction_day = get_next_auction_date(now_cairo)

    # Determine update reason
    if last_update_dt:
        days_since = (now_cairo.date() - last_update_dt.date()).days
        if days_since > 1:
            pass
        elif (
            now_cairo.weekday() in [3, 6] and last_update_dt.date() != now_cairo.date()
        ):
            pass
    else:
        pass

    # Update button logic - Always allow updates

    # Display main header
    # ملاحظة: تنسيق .light-hero-card أصبح في styles.css
    st.markdown(
        f"""
        <a id="top"></a>
        <div class="light-hero-card">
            <span class="hero-icon">🏦</span>
            <h1>{prepare_arabic_text(C.APP_TITLE)}</h1>
            <p>{prepare_arabic_text(C.APP_HEADER)}</p>
            <div class="author-info">صُمم بواسطة <span>{C.AUTHOR_NAME}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Calculate and display countdown
    time_to_auction = next_auction_dt - now_cairo
    countdown_str = format_countdown(time_to_auction)

    # Display auction card with status - Always show update available
    card_color = "update-message info"
    card_msg = "يمكنك تحديث البيانات الآن"

    auction_card = f"""
    <div class='card {card_color}'>
        <div class='next-auction-date-beauty'>
            <span>
                العطاء القادم: {next_auction_day} {next_auction_dt.strftime('%Y-%m-%d')}
            </span>
        </div>
        <div class='blinking-text countdown-remaining'>⏰ متبقي: {countdown_str}</div>
        <div class='card-msg'>{card_msg}</div>
    </div>
    """
    st.markdown(auction_card, unsafe_allow_html=True)

    # زر التحديث السريع مع بروجريس تفاعلي
    update_btn_clicked = st.button(
        "🔄 تحديث سريع",
        key="update_button_real",
        use_container_width=True,
        help="تحديث سريع للبيانات من قاعدة البيانات",
    )
    if update_btn_clicked:
        with st.spinner("🔄 جاري التحديث السريع..."):
            progress = st.progress(0, text="جاري تحديث البيانات...")
            for i in range(1, 101, 10):
                import time

                time.sleep(0.08)
                progress.progress(i, text=f"جاري تحديث البيانات... {i}%")
            update_data_async(force_refresh=True, is_force_update=False)
            progress.progress(100, text="تم التحديث!")
            st.rerun()

    # زر الانتقال إلى موقع البنك المركزي (بلون داكن وتفاعل hover)
    st.markdown(
        """
        </style>
        <div class='centered-container'>
            <a href="https://www.cbe.org.eg/ar/auctions/egp-t-bills" target="_blank">
                <button class="cbe-link-btn">🌐 الانتقال إلى موقع البنك المركزي - عطاءات أذون الخزانة</button>
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Display update status messages with better styling
    if st.session_state.get("update_status") == "updating":
        with st.container():
            st.info(st.session_state.get("update_message", "جاري التحديث..."))
    elif st.session_state.get("update_status") == "success":
        with st.container():
            st.success(st.session_state.get("update_message", "اكتمل التحديث!"))
        # Clear status after a short delay
        st.session_state.update_status = None
    elif st.session_state.get("update_status") == "failed":
        with st.container():
            st.error(st.session_state.get("update_message", "فشل التحديث."))
        # Clear status after a short delay
        st.session_state.update_status = None

    # Display auction results
    display_auction_results(
        "عطاء الخميس", "آجال (6 أشهر و 12 شهر)", data_df, [182, 364]
    )
    display_auction_results("عطاء الأحد", "آجال (3 أشهر و 9 أشهر)", data_df, [91, 273])

    # Back to top button
    st.markdown('<a href="#top" class="back-to-top">▲</a>', unsafe_allow_html=True)
