# ui/primary_yield_calculator.py
import streamlit as st
from factories import InputModelFactory
from treasury_core.calculations import calculate_primary_yield
from utils import prepare_arabic_text, format_currency, validate_face_value
from state_manager import Repository, StateManager
from treasury_core.models import PrimaryYieldResult
import constants as C
from tenors import active_tenors, calc_days
from decimal import Decimal
import ledger
from ui.portfolio import remember_calculation, render_save_to_ledger

# إنشاء خزان للنتائج
primary_results_repo = Repository[PrimaryYieldResult]("primary_yield")


def render_primary_yield_calculator():
    """عرض حاسبة العائد الأساسية"""
    with st.container():
        # ترتيب مربعات الإدخال في صف أفقي واحد من 4 أعمدة
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(
                """<div class='input-label'>القيمة الاسمية (جنيه)</div>""",
                unsafe_allow_html=True,
            )
            face_value = st.number_input(
                label="القيمة الاسمية",
                label_visibility="collapsed",
                min_value=0.0,
                max_value=10000000.0,
                value=25000.0,
                step=C.T_BILL_AMOUNT_STEP,
                format="%.1f",
            )
        with col2:
            st.markdown(
                """<div class='input-label'>معدل العائد (%)</div>""",
                unsafe_allow_html=True,
            )
            df_data = StateManager.get("df_data", None)
            default_yield = 25.0000
            if isinstance(default_yield, Decimal):
                default_yield_float = float(default_yield)
            else:
                default_yield_float = default_yield
            if "use_latest" in st.session_state:
                use_latest = st.session_state["use_latest"]
            else:
                use_latest = False
            if use_latest and df_data is not None and not df_data.empty:
                tenor_value = st.session_state.get("tenor", 91)
                filtered_df = df_data[df_data[C.TENOR_COLUMN_NAME] == tenor_value]
                value_for_input = (
                    float(filtered_df[C.YIELD_COLUMN_NAME].iloc[0])
                    if not filtered_df.empty
                    else default_yield_float
                )
                # في Streamlit الحديث، مع وجود key يتجاهل الحقل وسيط value بعد أول رسم،
                # فنكتب القيمة مباشرة في session_state قبل إنشاء الحقل.
                st.session_state["yield_rate_input"] = value_for_input
            else:
                value_for_input = default_yield_float
            _yield_kwargs = (
                {}
                if "yield_rate_input" in st.session_state
                else {"value": value_for_input}
            )
            yield_rate = st.number_input(
                label="معدل العائد",
                label_visibility="collapsed",
                min_value=0.001,
                max_value=50.0,
                step=0.001,
                format="%.3f",
                disabled=use_latest,
                key="yield_rate_input",
                **_yield_kwargs,
            )
        with col3:
            st.markdown(
                """<div class='input-label'>أجل الإذن (يوم)</div>""",
                unsafe_allow_html=True,
            )
            tenor_options = active_tenors(
                st.session_state.get("_df_data_for_tenors"), C.TENORS
            )
            tenor = st.selectbox(
                label="أجل الإذن",
                label_visibility="collapsed",
                options=tenor_options,
                index=0,
                format_func=lambda x: f"{x} يوم",
            )
            if (
                "tenor" not in st.session_state
                or st.session_state.get("tenor") != tenor
            ):
                st.session_state["tenor"] = tenor
                if use_latest and df_data is not None and not df_data.empty:
                    st.rerun()
        with col4:
            st.markdown(
                """<div class='input-label'>معدل الضريبة (%)</div>""",
                unsafe_allow_html=True,
            )
            tax_rate = st.number_input(
                label="معدل الضريبة",
                label_visibility="collapsed",
                min_value=0.0,
                max_value=100.0,
                value=C.DEFAULT_TAX_RATE_PERCENT,
                step=0.1,
                format="%.1f",
            )
        # بعد صف الأعمدة الأربعة، أضف خيار استخدام أحدث عائد متاح في منتصف الصفحة
        st.markdown(
            "<div class='centered-container'></div>",
            unsafe_allow_html=True,
        )
        use_latest = st.checkbox(
            prepare_arabic_text("استخدام أحدث عائد متاح"),
            value=use_latest,
            key="use_latest",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        face_value_error = validate_face_value(face_value)
        if face_value_error:
            st.error(prepare_arabic_text(face_value_error))

        # زر الحساب وسط الشاشة
        calculate_button = st.button(
            prepare_arabic_text("💰 احسب العائد"),
            type="primary",
            width="stretch",
            disabled=bool(face_value_error),
        )

    if calculate_button:
        try:
            with st.spinner(prepare_arabic_text("جاري الحساب...")):
                input_model = InputModelFactory.create_primary_yield_input(
                    {
                        "face_value": face_value,
                        "yield_rate": yield_rate,
                        "tenor": calc_days(
                            tenor, st.session_state.get("_df_data_for_tenors")
                        ),
                        "tax_rate": tax_rate,
                    }
                )
                result = calculate_primary_yield(input_model)
                primary_results_repo.save("latest", result)
                _days = calc_days(tenor, st.session_state.get("_df_data_for_tenors"))
                remember_calculation(face_value, yield_rate, _days, tax_rate, result)
                display_primary_results(
                    result,
                    face_value,
                    yield_rate,
                    calc_days(tenor, st.session_state.get("_df_data_for_tenors")),
                    tax_rate,
                )
        except Exception as e:
            st.error(f"خطأ في الحساب: {str(e)}")
    elif not face_value_error and primary_results_repo.exists("latest"):
        display_primary_results(primary_results_repo.get("latest"))

    if primary_results_repo.exists("latest"):
        render_save_to_ledger()


def display_primary_results(
    result, face_value=None, yield_rate=None, tenor=None, tax_rate=None
):
    """عرض نتائج حساب العائد الأساسي."""
    st.markdown(
        "<div class='card--section-header'><h2 class='section-title'>نتائج الحساب الأساسية</h2></div>",
        unsafe_allow_html=True,
    )

    # Row 1 for the new card
    if face_value is not None:
        total_value = face_value + result.net_return
        st.markdown(
            f"<div class='metric-card-container-centered'><div class='metric-card gold'><span class='metric-title'>إجمالي القيمة بعد الربح</span><span class='metric-value'>{format_currency(total_value)}</span></div></div>",
            unsafe_allow_html=True,
        )

    # Row 2
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"<div class='metric-card blue'><span class='metric-title'>سعر الشراء</span><span class='metric-value'>{format_currency(result.purchase_price)}</span></div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div class='metric-card green-dark'><span class='metric-title'>العائد الإجمالي</span><span class='metric-value'>{format_currency(result.gross_return)}</span></div>",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"<div class='metric-card red'><span class='metric-title'>الضريبة المستحقة</span><span class='metric-value'>{format_currency(result.tax_amount)}</span></div>",
            unsafe_allow_html=True,
        )

    # Row 3
    col4, col5, col6 = st.columns(3)
    with col4:
        st.markdown(
            f"<div class='metric-card green-light'><span class='metric-title'>صافي الربح</span><span class='metric-value'>{format_currency(result.net_return)}</span></div>",
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            f"<div class='metric-card purple'><span class='metric-title'>إجمالي المبلغ عند الاستحقاق</span><span class='metric-value'>{format_currency(result.total_payout)}</span></div>",
            unsafe_allow_html=True,
        )
    with col6:
        st.markdown(
            f"<div class='metric-card cyan'><span class='metric-title'>نسبة الربح الحقيقية</span><span class='metric-value'>{result.real_profit_percentage:.2f}%</span></div>",
            unsafe_allow_html=True,
        )

    if face_value is not None and tenor:
        fees = ledger.fee_estimates(float(face_value), int(tenor))
        st.markdown(
            f"<div class='metric-card-container-centered'><div class='metric-card cyan'>"
            f"<span class='metric-title'>صافي الربح بعد الرسوم (تقدير)</span>"
            f"<span class='metric-value'>{format_currency(result.net_return - fees['total'])}</span></div></div>",
            unsafe_allow_html=True,
        )

    st.info(
        "تذكر أن قيمة الإذن عند الاستحقاق ثابتة وهي القيمة الاسمية، بينما يختلف سعر الشراء حسب معدل العائد."
    )

    # قسم شرح المعادلات (قابل للطي)
    with st.expander("🔍 شرح المعادلات والمصطلحات"):
        st.markdown("<h4>كيف يتم حساب العائد الأساسي؟</h4>", unsafe_allow_html=True)
        st.markdown(
            "🧮 **سعر الشراء** = القيمة الاسمية ÷ [1 + (معدل العائد × الأجل ÷ 365)]"
        )
        st.markdown("💰 **العائد الإجمالي** = القيمة الاسمية - سعر الشراء")
        st.markdown("💸 **الضريبة المستحقة** = العائد الإجمالي × معدل الضريبة ÷ 100")
        st.markdown("✅ **صافي الربح** = العائد الإجمالي - الضريبة المستحقة")
        st.markdown("📊 **إجمالي المبلغ عند الاستحقاق** = القيمة الاسمية + صافي الربح")
        st.markdown("🎯 **نسبة الربح الحقيقية** = (صافي الربح ÷ سعر الشراء) × 100")

        st.info(
            "💡 **ملاحظة مهمة:** معادلة سعر الشراء تحسب المبلغ الذي يجب دفعه اليوم للحصول على القيمة الاسمية عند الاستحقاق. كلما زاد العائد، انخفض سعر الشراء."
        )
    # The results-card div is closed within its own markdown string.
    # st.markdown("</div>", unsafe_allow_html=True) # This was causing an extra empty card.
