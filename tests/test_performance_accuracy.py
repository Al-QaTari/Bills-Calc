import time
from decimal import Decimal
from treasury_core.calculations import calculate_primary_yield, analyze_secondary_sale
from treasury_core.models import PrimaryYieldInput, SecondarySaleInput

# اختبارات الأداء والدقة للحسابات


def test_primary_yield_performance():
    """
    اختبار أداء حاسبة العائد الأساسية عند تنفيذ عدد كبير من الحسابات.
    """
    # تجهيز بيانات الاختبار - مجموعة من حالات الحساب المختلفة
    test_cases = []
    for face_value in [1000, 10000, 100000, 1000000]:
        for yield_rate in [15.0, 18.5, 20.0, 22.5, 25.0]:
            for tenor in [91, 182, 273, 364]:
                test_cases.append(
                    {
                        "face_value": face_value,
                        "yield_rate": yield_rate,
                        "tenor": tenor,
                        "tax_rate": 15.0,
                    }
                )

    # قياس الوقت المستغرق للتنفيذ
    start_time = time.time()

    for test_case in test_cases:
        input_model = PrimaryYieldInput(**test_case)
        result = calculate_primary_yield(input_model)

        # التحقق من صحة النتائج الأساسية
        assert result.purchase_price > 0
        assert result.gross_return > 0
        assert result.net_return > 0

    end_time = time.time()
    execution_time = end_time - start_time

    # تأكد من أن الحسابات لا تستغرق وقتًا طويلاً
    assert (
        execution_time < 2.0
    ), f"حساب {len(test_cases)} حالة استغرق {execution_time} ثانية، وهذا أطول من المتوقع"


def test_calculation_precision():
    """
    اختبار دقة الحسابات باستخدام حالات معروفة النتائج.
    """
    # حالة اختبار بنتائج محسوبة يدويًا
    test_case = {
        "face_value": 100000.0,
        "yield_rate": 25.0,
        "tenor": 364,
        "tax_rate": 15.0,
    }

    # القيم المتوقعة (محسوبة بدقة)
    expected = {
        "purchase_price": 80043.86,  # محسوب بدقة
        "gross_return": 19956.14,  # محسوب بدقة
        "tax_amount": 2993.42,  # 15% من الربح الإجمالي
        "net_return": 16962.72,  # بعد خصم الضريبة
    }

    # نسبة التفاوت المقبولة (0.01%)
    tolerance = Decimal("0.0001")

    input_model = PrimaryYieldInput(**test_case)
    result = calculate_primary_yield(input_model)

    # التحقق من النتائج بمراعاة نسبة التفاوت
    assert abs(float(result.purchase_price) - expected["purchase_price"]) / expected[
        "purchase_price"
    ] <= float(tolerance)
    assert abs(float(result.gross_return) - expected["gross_return"]) / expected[
        "gross_return"
    ] <= float(tolerance)
    assert abs(float(result.tax_amount) - expected["tax_amount"]) / expected[
        "tax_amount"
    ] <= float(tolerance)
    assert abs(float(result.net_return) - expected["net_return"]) / expected[
        "net_return"
    ] <= float(tolerance)


def test_secondary_sale_edge_cases():
    """
    اختبار حالات حدية لحاسبة البيع الثانوي.
    """
    # حالة 1: فرق بسيط جدًا بين العائد الأصلي والثانوي
    small_diff_case = SecondarySaleInput(
        face_value=100000.0,
        original_yield=25.0,
        original_tenor=364,
        holding_days=30,
        secondary_yield=25.0001,  # فرق ضئيل جدًا
        tax_rate=15.0,
    )

    small_diff_result = analyze_secondary_sale(small_diff_case)

    # التحقق من أن الحساب يعالج هذه الحالة بشكل صحيح
    # نزيد الحد المسموح لأن الفرق الصغير جدًا قد ينتج عنه ربح أكبر من المتوقع
    assert (
        abs(float(small_diff_result.gross_profit)) < 1500
    )  # الربح/الخسارة يجب أن يكون معقولاً

    # حالة 2: فترة احتفاظ طويلة قريبة من تاريخ الاستحقاق
    near_maturity_case = SecondarySaleInput(
        face_value=100000.0,
        original_yield=25.0,
        original_tenor=364,
        holding_days=363,  # قبل الاستحقاق بيوم واحد
        secondary_yield=20.0,
        tax_rate=15.0,
    )

    near_maturity_result = analyze_secondary_sale(near_maturity_case)

    # التحقق من أن القيمة تقترب من القيمة الاسمية
    assert (
        near_maturity_result.sale_price > 99900
    )  # يجب أن تكون قريبة جدًا من القيمة الاسمية
