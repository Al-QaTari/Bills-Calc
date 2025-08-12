# -*- coding: utf-8 -*-
"""
Streamlit UI module for the Secondary Sale Calculator.

This module provides the user interface to analyze the secondary market sale
of treasury bills, calculating potential profits or losses based on various inputs.
"""

from datetime import datetime, timedelta

import streamlit as st

import constants as C
from factories import InputModelFactory
from state_manager import Repository
from treasury_core.calculations import analyze_secondary_sale
from treasury_core.models import SecondarySaleResult
from utils import format_currency, prepare_arabic_text

# Initialize a repository to persist secondary sale results in the session state
secondary_results_repo = Repository[SecondarySaleResult]("secondary_sale")


def display_secondary_results(result: SecondarySaleResult):
    """
    Displays the results of the secondary sale analysis in styled metric cards.

    Args:
        result: The SecondarySaleResult object containing calculation outputs.
    """
    st.markdown(
        "<div class='card--section-header'><h2 class='section-title'>"
        "نتائج تحليل البيع الثانوي</h2></div>",
        unsafe_allow_html=True,
    )

    # Row 1: Purchase Price, Sale Price, Gross Profit
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"<div class='metric-card blue'><span class='metric-title'>"
            f"سعر الشراء الأصلي</span><span class='metric-value'>"
            f"{format_currency(result.original_purchase_price)}</span></div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div class='metric-card yellow'><span class='metric-title'>"
            f"سعر البيع الثانوي</span><span class='metric-value'>"
            f"{format_currency(result.sale_price)}</span></div>",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"<div class='metric-card green-dark'><span class='metric-title'>"
            f"الربح/الخسارة الإجمالية</span><span class='metric-value'>"
            f"{format_currency(result.gross_profit)}</span></div>",
            unsafe_allow_html=True,
        )

    # Row 2: Tax, Net Profit, Period Yield
    col4, col5, col6 = st.columns(3)
    with col4:
        st.markdown(
            f"<div class='metric-card red'><span class='metric-title'>"
            f"الضريبة المستحقة</span><span class='metric-value'>"
            f"{format_currency(result.tax_amount)}</span></div>",
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f"<div class='metric-card green-light'><span class='metric-title'>"
            f"صافي الربح/الخسارة</span><span class='metric-value'>"
            f"{format_currency(result.net_profit)}</span></div>",
            unsafe_allow_html=True,
        )
    with col6:
        st.markdown(
            f"<div class='metric-card cyan'><span class='metric-title'>"
            f"نسبة العائد للفترة</span><span class='metric-value'>"
            f"{result.period_yield:.2f}%</span></div>",
            unsafe_allow_html=True,
        )

    st.info(
        "ملاحظة: صافي الربح/الخسارة هو الفرق النهائي بعد احتساب الضريبة وجميع العوامل."
    )


def render_secondary_sale_calculator():
    """Renders the secondary sale calculator interface and handles user interactions."""
    with st.container():
        df_data = st.session_state.get("df_data")
        use_latest_original = st.session_state.get("use_latest_original", False)

        # --- Input Fields ---
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        with row1_col1:
            face_value = st.number_input(
                prepare_arabic_text("القيمة الاسمية (جنيه)"),
                min_value=C.MIN_T_BILL_AMOUNT,
                value=25000.0,
                step=C.T_BILL_AMOUNT_STEP,
                format="%.1f",
                key="sec_face_value",
            )
        with row1_col3:
            original_tenor = st.selectbox(
                prepare_arabic_text("أجل الإذن الأصلي"),
                [91, 182, 273, 364],
                key="sec_tenor",
            )

        with row1_col2:
            original_yield_value = st.session_state.get("sec_orig_yield", 25.0)
            if use_latest_original and df_data is not None and not df_data.empty:
                filtered_df = df_data[df_data[C.TENOR_COLUMN_NAME] == original_tenor]
                if not filtered_df.empty:
                    original_yield_value = float(
                        filtered_df[C.YIELD_COLUMN_NAME].iloc[0]
                    )

            original_yield = st.number_input(
                prepare_arabic_text("معدل العائد الأصلي (%)"),
                min_value=1.0,
                value=original_yield_value,
                step=0.001,
                format="%.3f",
                key="sec_orig_yield",
                disabled=use_latest_original,
            )

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            max_holding = original_tenor - 1
            holding_days = st.number_input(
                prepare_arabic_text("عدد أيام الاحتفاظ"),
                min_value=1,
                max_value=max_holding,
                value=min(30, max_holding),
                step=1,
                key="sec_holding",
            )
        with row2_col2:
            tax_rate = st.number_input(
                prepare_arabic_text("معدل الضريبة (%)"),
                min_value=0.0,
                value=C.DEFAULT_TAX_RATE_PERCENT,
                step=0.1,
                format="%.1f",
                key="sec_tax",
            )
        with row2_col3:
            secondary_yield = st.number_input(
                prepare_arabic_text("معدل العائد الثانوي (%)"),
                min_value=1.0,
                value=24.0,
                step=0.001,
                format="%.3f",
                key="sec_sec_yield",
            )

        use_latest_original = st.checkbox(
            prepare_arabic_text("استخدام أحدث عائد متاح"),
            value=use_latest_original,
            key="use_latest_original",
        )

    # --- Dynamic Date Calculation (Updated Logic) ---
    sale_date = datetime.now()
    purchase_date = sale_date - timedelta(days=holding_days)
    remaining_days = original_tenor - holding_days
    maturity_date = sale_date + timedelta(days=remaining_days)

    st.markdown(
        f"""
        <div class="date-cards-container">
            <div class="date-card">
                <div class="date-title">تاريخ الشراء</div>
                <div class="date-value">{purchase_date.strftime('%d-%m-%Y')}</div>
            </div>
            <div class="date-card">
                <div class="date-title">تاريخ البيع (اليوم)</div>
                <div class="date-value">{sale_date.strftime('%d-%m-%Y')}</div>
            </div>
            <div class="date-card">
                <div class="date-title">تاريخ الاستحقاق</div>
                <div class="date-value">{maturity_date.strftime('%d-%m-%Y')}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    calculate_button = st.button(
        "💸 تحليل البيع الثانوي", type="primary", use_container_width=True
    )

    result_to_display = None

    if calculate_button:
        try:
            with st.spinner("جاري تحليل البيع..."):
                inputs = {
                    "face_value": face_value,
                    "original_yield": original_yield,
                    "original_tenor": original_tenor,
                    "holding_days": holding_days,
                    "secondary_yield": secondary_yield,
                    "tax_rate": tax_rate,
                }
                input_model = InputModelFactory.create_secondary_sale_input(inputs)
                result = analyze_secondary_sale(input_model)

                secondary_results_repo.save("latest", result)
                secondary_results_repo.save("inputs", inputs)
                result_to_display = result

        except Exception as e:
            st.error(f"خطأ في التحليل: {e}")

    else:
        # On first load or rerun, try to get the last saved result
        result_to_display = secondary_results_repo.get("latest")

    if result_to_display:
        display_secondary_results(result_to_display)

    # --- قسم شرح المعادلات (قابل للطي) ---
    with st.expander("🔍 شرح المعادلات والمصطلحات"):
        st.markdown("<h4>كيف يتم حساب البيع الثانوي؟</h4>", unsafe_allow_html=True)
        st.markdown(
            "🧮 **سعر الشراء الأصلي** = القيمة الاسمية ÷ [1 + (معدل العائد الأصلي × الأجل الأصلي ÷ 365)]"
        )
        st.markdown(
            "💸 **سعر البيع الثانوي** = القيمة الاسمية ÷ [1 + (معدل العائد الثانوي × الأيام المتبقية ÷ 365)]"
        )
        st.markdown("📊 **الأيام المتبقية** = الأجل الأصلي - عدد أيام الاحتفاظ")
        st.markdown(
            "💰 **الربح/الخسارة** = سعر البيع الثانوي - سعر الشراء الأصلي - الضريبة"
        )

        st.info(
            "💡 **ملاحظة مهمة:** معادلة البيع الثانوي تحسب السعر الذي يجب بيعه به لتحقيق العائد المطلوب في السوق الثانوي. كلما زاد العائد الثانوي، انخفض سعر البيع."
        )
