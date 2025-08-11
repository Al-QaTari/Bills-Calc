# ui/secondary_sale_calculator.py
import streamlit as st
from factories import InputModelFactory
from treasury_core.calculations import analyze_secondary_sale
from utils import prepare_arabic_text, format_currency
from state_manager import Repository
from treasury_core.models import SecondarySaleResult
import constants as C
from datetime import datetime, timedelta

secondary_results_repo = Repository[SecondarySaleResult]("secondary_sale")


def display_secondary_results(
    result: SecondarySaleResult,
    face_value: float,
    original_yield: float,
    original_tenor: int,
    tax_rate: float,
    secondary_yield: float = None,
):
    """عرض نتائج تحليل البيع الثانوي."""
    st.markdown(
        "<div class='card--section-header'><h2 class='section-title'>نتائج تحليل البيع الثانوي</h2></div>",
        unsafe_allow_html=True,
    )

    # Row 1
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"<div class='metric-card blue'><span class='metric-title'>سعر الشراء الأصلي</span><span class='metric-value'>{format_currency(result.original_purchase_price)}</span></div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div class='metric-card yellow'><span class='metric-title'>سعر البيع الثانوي</span><span class='metric-value'>{format_currency(result.sale_price)}</span></div>",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"<div class='metric-card green-dark'><span class='metric-title'>الربح/الخسارة الإجمالية</span><span class='metric-value'>{format_currency(result.gross_profit)}</span></div>",
            unsafe_allow_html=True,
        )

    # Row 2
    col4, col5, col6 = st.columns(3)
    with col4:
        st.markdown(
            f"<div class='metric-card red'><span class='metric-title'>الضريبة المستحقة</span><span class='metric-value'>{format_currency(result.tax_amount)}</span></div>",
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f"<div class='metric-card green-light'><span class='metric-title'>صافي الربح/الخسارة</span><span class='metric-value'>{format_currency(result.net_profit)}</span></div>",
            unsafe_allow_html=True,
        )
    with col6:
        st.markdown(
            f"<div class='metric-card cyan'><span class='metric-title'>نسبة العائد للفترة</span><span class='metric-value'>{result.period_yield:.2f}%</span></div>",
            unsafe_allow_html=True,
        )

    st.info(
        "ملاحظة: صافي الربح/الخسارة هو الفرق النهائي بعد احتساب الضريبة وجميع العوامل."
    )


def render_secondary_sale_calculator():
    """عرض حاسبة تحليل البيع الثانوي"""
    with st.container():
        # --- تعريف متغير use_latest_original في البداية ---
        df_data = st.session_state.get("df_data", None)
        if "use_latest_original" in st.session_state:
            use_latest_original = st.session_state["use_latest_original"]
        else:
            use_latest_original = False

        # الصف الأول: القيمة الاسمية | معدل العائد الأصلي | أجل الإذن الأصلي
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
            # حساب قيمة العائد الأصلي بناءً على الخيار
            if use_latest_original and df_data is not None and not df_data.empty:
                filtered_df = df_data[df_data[C.TENOR_COLUMN_NAME] == original_tenor]
                original_yield_value = (
                    float(filtered_df[C.YIELD_COLUMN_NAME].iloc[0])
                    if not filtered_df.empty
                    else 25.0
                )
            else:
                original_yield_value = st.session_state.get("sec_orig_yield", 25.0)

            # إدخال معدل العائد الأصلي
            original_yield = st.number_input(
                prepare_arabic_text("معدل العائد الأصلي (%)"),
                min_value=1.0,
                value=original_yield_value,
                step=0.001,
                format="%.3f",
                key="sec_orig_yield",
                disabled=use_latest_original,
            )

        # الصف الثاني: عدد أيام الاحتفاظ | معدل الضريبة | معدل العائد الثانوي
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
        st.markdown("</div>", unsafe_allow_html=True)

        # --- زر استخدام أحدث عائد متاح أسفل المربعات ---
        use_latest_original = st.checkbox(
            prepare_arabic_text("استخدام أحدث عائد متاح"),
            value=use_latest_original,
            key="use_latest_original",
        )

    # --- حساب التواريخ ديناميكيًا ---
    purchase_date = datetime.now()
    sale_date = purchase_date + timedelta(days=holding_days)
    maturity_date = purchase_date + timedelta(days=original_tenor)

    st.markdown(
        f"""
        <div class="date-cards-container">
            <div class="date-card">
                <div class="date-title">تاريخ الشراء</div>
                <div class="date-value">{purchase_date.strftime('%d-%m-%Y')}</div>
            </div>
            <div class="date-card">
                <div class="date-title">تاريخ البيع</div>
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

    if calculate_button:
        try:
            with st.spinner("جاري تحليل البيع..."):
                input_model = InputModelFactory.create_secondary_sale_input(
                    {
                        "face_value": face_value,
                        "original_yield": original_yield,
                        "original_tenor": original_tenor,
                        "holding_days": holding_days,
                        "secondary_yield": secondary_yield,
                        "tax_rate": tax_rate,
                    }
                )
                result = analyze_secondary_sale(input_model)
                secondary_results_repo.save("latest", result)
                # حفظ القيم المدخلة مع النتائج
                secondary_results_repo.save(
                    "inputs",
                    {
                        "face_value": face_value,
                        "original_yield": original_yield,
                        "original_tenor": original_tenor,
                        "tax_rate": tax_rate,
                        "secondary_yield": secondary_yield,
                    },
                )
                display_secondary_results(
                    result,
                    face_value,
                    original_yield,
                    original_tenor,
                    tax_rate,
                    secondary_yield,
                )
        except Exception as e:
            st.error(f"خطأ في التحليل: {str(e)}")

    elif secondary_results_repo.exists("latest"):
        latest_result = secondary_results_repo.get("latest")
        saved_inputs = secondary_results_repo.get("inputs")
        if latest_result and saved_inputs:
            display_secondary_results(
                latest_result,
                saved_inputs.get("face_value", 25000),
                saved_inputs.get("original_yield", 25.0),
                saved_inputs.get("original_tenor", 91),
                saved_inputs.get("tax_rate", 20.0),
                saved_inputs.get("secondary_yield", 24.0),
            )

    # قسم شرح المعادلات (قابل للطي)
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
