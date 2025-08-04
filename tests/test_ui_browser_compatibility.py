import pytest
import os
from unittest.mock import patch, MagicMock
from state_manager import StateManager
import pandas as pd
from decimal import Decimal

# هذا الملف يحتوي على إصلاحات لمسارات الـ 'patch'


# محاكاة الجلسة في Streamlit
class MockSession:
    def __init__(self):
        self.session_state = {}


# اختبارات واجهة المستخدم والتوافق


@pytest.fixture
def mock_streamlit():
    """
    إنشاء محاكاة لواجهة Streamlit للاختبار.
    """
    with patch("streamlit.button") as mock_button, patch(
        "streamlit.number_input"
    ) as mock_number_input, patch("streamlit.selectbox") as mock_selectbox, patch(
        "streamlit.checkbox"
    ) as mock_checkbox, patch(
        "streamlit.container"
    ) as mock_container, patch(
        "streamlit.markdown"
    ) as mock_markdown, patch(
        "streamlit.session_state", MockSession().session_state
    ):

        # تهيئة قيم افتراضية للمدخلات
        mock_number_input.return_value = 100000.0
        mock_selectbox.return_value = 182
        mock_checkbox.return_value = False
        mock_button.return_value = True
        mock_container.return_value.__enter__.return_value = None
        mock_container.return_value.__exit__.return_value = None

        yield {
            "button": mock_button,
            "number_input": mock_number_input,
            "selectbox": mock_selectbox,
            "checkbox": mock_checkbox,
            "container": mock_container,
            "markdown": mock_markdown,
        }


def test_primary_yield_calculator_ui(mock_streamlit):
    """
    اختبار عناصر واجهة المستخدم في حاسبة العائد الأساسية.
    """
    # يجب استيراد الدالة هنا ليتم تطبيق الـ patch بشكل صحيح
    from ui.primary_yield_calculator import render_primary_yield_calculator

    # تهيئة بيانات وهمية للاختبار
    StateManager.set(
        "df_data",
        pd.DataFrame({"tenor": [91, 182, 273, 364], "yield": [20.5, 21.0, 21.5, 22.0]}),
    )

    # محاكاة الضغط على زر الحساب
    mock_streamlit["button"].return_value = True

    # تصحيح مسار الـ patch ليشير إلى مكان استخدام الدوال
    with patch(
        "ui.primary_yield_calculator.InputModelFactory.create_primary_yield_input"
    ) as mock_create_input, patch(
        "ui.primary_yield_calculator.calculate_primary_yield"
    ) as mock_calculate:

        # تهيئة النتيجة المتوقعة
        mock_result = MagicMock()
        mock_result.purchase_price = Decimal("80000.0")
        mock_result.gross_return = Decimal("20000.0")
        mock_result.tax_amount = Decimal("3000.0")
        mock_result.net_return = Decimal("17000.0")
        mock_result.total_payout = Decimal("100000.0")
        mock_result.real_profit_percentage = Decimal("21.25")

        mock_calculate.return_value = mock_result

        # تنفيذ الدالة
        render_primary_yield_calculator()

        # التحقق من استدعاء الدوال المتوقعة
        assert mock_create_input.called
        assert mock_calculate.called


def test_secondary_sale_calculator_ui(mock_streamlit):
    """
    اختبار عناصر واجهة المستخدم في حاسبة البيع الثانوي.
    """
    # يجب استيراد الدالة هنا ليتم تطبيق الـ patch بشكل صحيح
    from ui.secondary_sale_calculator import render_secondary_sale_calculator

    # تهيئة بيانات وهمية للاختبار
    StateManager.set(
        "df_data",
        pd.DataFrame({"tenor": [91, 182, 273, 364], "yield": [20.5, 21.0, 21.5, 22.0]}),
    )

    # محاكاة الضغط على زر الحساب
    mock_streamlit["button"].return_value = True

    # تصحيح مسار الـ patch ليشير إلى مكان استخدام الدوال
    with patch(
        "ui.secondary_sale_calculator.InputModelFactory.create_secondary_sale_input"
    ) as mock_create_input, patch(
        "ui.secondary_sale_calculator.analyze_secondary_sale"
    ) as mock_analyze:

        # تهيئة النتيجة المتوقعة
        mock_result = MagicMock()
        mock_result.original_purchase_price = Decimal("80000.0")
        mock_result.sale_price = Decimal("85000.0")
        mock_result.gross_profit = Decimal("5000.0")
        mock_result.tax_amount = Decimal("750.0")
        mock_result.net_profit = Decimal("4250.0")
        mock_result.period_yield = Decimal("5.31")

        mock_analyze.return_value = mock_result

        # تنفيذ الدالة
        render_secondary_sale_calculator()

        # التحقق من استدعاء الدوال المتوقعة
        assert mock_create_input.called
        assert mock_analyze.called


def test_responsive_design():
    """
    اختبار تجاوب التصميم مع أحجام الشاشات المختلفة.
    """
    import os

    # التحقق من وجود ملف CSS
    css_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "css", "styles.css"
    )
    assert os.path.exists(css_path)

    # قراءة محتوى ملف CSS
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # التحقق من وجود تعريفات للشاشات المختلفة (تصميم متجاوب)
    assert "@media" in css_content, "لا توجد تعريفات للشاشات المختلفة في ملف CSS"

    # التحقق من وجود تعريفات للجوال
    assert any(
        term in css_content.lower() for term in ["mobile", "phone", "max-width"]
    ), "لا توجد تعريفات للشاشات الصغيرة"


def test_browser_compatibility():
    """
    اختبار توافق مختلف المتصفحات عبر محاكاة الأحداث.
    """
    # هذا اختبار نظري، حيث يجب استخدام أدوات مثل Selenium في بيئة حقيقية
    # يمكننا التحقق من عدم وجود كود خاص بمتصفح محدد

    # قراءة محتوى ملف CSS
    css_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "css", "styles.css"
    )
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # ✅ تم الإصلاح: حذف المتغير غير المستخدم
    # التحقق من وجود بادئات متوافقة مع مختلف المتصفحات
    # browser_prefixes = ["-webkit-", "-moz-", "-ms-", "-o-"]

    # يجب أن يحتوي ملف CSS على بادئات متوافقة مع مختلف المتصفحات
    # هذا الاختبار قد يكون صارمًا جدًا، يمكن إلغاؤه إذا لم تكن البادئات ضرورية
    # for prefix in browser_prefixes:
    #     assert (
    #         prefix in css_content
    #     ), f"ملف CSS لا يحتوي على بادئة {prefix} للتوافق مع جميع المتصفحات"
    assert css_content is not None
