import pandas as pd
from decimal import Decimal
from treasury_core.calculations import calculate_primary_yield, analyze_secondary_sale
from treasury_core.models import PrimaryYieldInput
from factories import InputModelFactory
import constants as C
from state_manager import StateManager

# اختبارات المقارنة والتكامل

# بيانات اختبار مرجعية (يمكن استبدالها ببيانات رسمية من البنك المركزي المصري)
REFERENCE_DATA = [
    {
        "face_value": 100000.0,
        "yield_rate": 25.0,
        "tenor": 364,
        "tax_rate": 15.0,
        "expected_purchase_price": 80000.0,
        "expected_net_return": 17000.0,
    },
    {
        "face_value": 100000.0,
        "yield_rate": 20.0,
        "tenor": 182,
        "tax_rate": 15.0,
        "expected_purchase_price": 90090.0,
        "expected_net_return": 7708.02,
    },
]


def test_calculation_against_reference():
    """
    اختبار مقارنة حسابات التطبيق مع بيانات مرجعية.
    """
    for ref_case in REFERENCE_DATA:
        # تجهيز بيانات الإدخال
        input_data = {
            "face_value": ref_case["face_value"],
            "yield_rate": ref_case["yield_rate"],
            "tenor": ref_case["tenor"],
            "tax_rate": ref_case["tax_rate"],
        }

        # تنفيذ الحساب
        input_model = PrimaryYieldInput(**input_data)
        result = calculate_primary_yield(input_model)

        # التحقق من النتائج مع مراعاة نسبة تفاوت 1%
        tolerance = 0.01

        # التحقق من سعر الشراء
        actual_purchase_price = float(result.purchase_price)
        expected_purchase_price = float(ref_case["expected_purchase_price"])
        assert (
            abs(actual_purchase_price - expected_purchase_price)
            <= expected_purchase_price * tolerance
        ), f"سعر الشراء {actual_purchase_price} لا يتطابق مع القيمة المتوقعة {expected_purchase_price} ضمن نسبة التفاوت {tolerance}"

        # التحقق من صافي العائد
        actual_net_return = float(result.net_return)
        expected_net_return = float(ref_case["expected_net_return"])
        assert (
            abs(actual_net_return - expected_net_return)
            <= expected_net_return * tolerance
        ), f"صافي العائد {actual_net_return} لا يتطابق مع القيمة المتوقعة {expected_net_return} ضمن نسبة التفاوت {tolerance}"


def test_end_to_end_calculation_flow():
    """
    اختبار تكاملي للتدفق الكامل من الإدخال إلى المخرجات.
    """
    # تهيئة بيانات الإدخال
    input_data = {
        "face_value": 100000.0,
        "yield_rate": 22.5,
        "tenor": 182,
        "tax_rate": 15.0,
    }

    # 1. إنشاء نموذج الإدخال
    input_model = InputModelFactory.create_primary_yield_input(input_data)
    assert input_model.face_value == Decimal(str(input_data["face_value"]))
    assert input_model.yield_rate == Decimal(str(input_data["yield_rate"]))

    # 2. حساب العائد الأساسي
    primary_result = calculate_primary_yield(input_model)
    assert primary_result.purchase_price > 0
    assert primary_result.net_return > 0

    # 3. استخدام نتائج الحساب الأساسي في حاسبة البيع الثانوي
    secondary_input_data = {
        "face_value": 100000.0,
        "original_yield": 22.5,
        "original_tenor": 182,
        "holding_days": 30,
        "secondary_yield": 21.0,  # عائد ثانوي أقل (سعر أعلى)
        "tax_rate": 15.0,
    }

    secondary_input = InputModelFactory.create_secondary_sale_input(
        secondary_input_data
    )
    secondary_result = analyze_secondary_sale(secondary_input)

    # 4. التحقق من اتساق النتائج - يجب أن يكون هناك ربح عند انخفاض العائد
    assert secondary_result.gross_profit > 0
    assert secondary_result.net_profit > 0


def test_data_flow_integration():
    """
    اختبار تكامل تدفق البيانات بين مكونات النظام.
    """
    # تهيئة بيانات تاريخية وهمية
    historical_df = pd.DataFrame(
        {
            "date": ["2023-01-01", "2023-01-01", "2023-01-01", "2023-01-01"],
            "tenor": [91, 182, 273, 364],
            "yield": [20.5, 21.0, 21.5, 22.0],
        }
    )

    # تخزين البيانات في مدير الحالة
    StateManager.set("historical_df", historical_df)

    # استخراج أحدث البيانات (محاكاة لما يحدث في app.py)
    latest_indices = historical_df.loc[historical_df.groupby("tenor")["date"].idxmax()]

    # تخزين أحدث البيانات في مدير الحالة
    StateManager.set("df_data", latest_indices.reset_index(drop=True))

    # التحقق من وجود البيانات
    df_data = StateManager.get("df_data")
    assert df_data is not None
    assert not df_data.empty
    assert "yield" in df_data.columns
    assert "tenor" in df_data.columns

    # التحقق من صحة عملية الترشيح - وجود جميع الآجال
    assert set(df_data["tenor"]) == set([91, 182, 273, 364])


def test_state_consistency():
    """
    اختبار اتساق حالة التطبيق بين مختلف المكونات.
    """
    # تهيئة بيانات وهمية
    tenor_value = 182
    yield_value = Decimal("21.0")

    # تخزين القيم في حالة الجلسة
    StateManager.set("tenor", tenor_value)

    # تهيئة بيانات مرجعية
    df_data = pd.DataFrame(
        {
            "tenor": [91, 182, 273, 364],
            "yield": [
                Decimal("20.5"),
                Decimal("21.0"),
                Decimal("21.5"),
                Decimal("22.0"),
            ],
        }
    )
    StateManager.set("df_data", df_data)

    # الحصول على العائد المناسب للأجل المخزن (محاكاة لما يحدث في primary_yield_calculator.py)
    filtered_df = df_data[df_data[C.TENOR_COLUMN_NAME] == tenor_value]
    retrieved_yield = (
        filtered_df[C.YIELD_COLUMN_NAME].iloc[0] if not filtered_df.empty else None
    )

    # التحقق من اتساق القيم
    assert retrieved_yield is not None
    assert retrieved_yield == yield_value
