"""
Accuracy Verification Tests for Treasury Bills Calculator
اختبارات التحقق من دقة حاسبة أذون الخزانة
"""

import pytest
from decimal import getcontext
from treasury_core.calculations import calculate_primary_yield, analyze_secondary_sale
from treasury_core.models import PrimaryYieldInput, SecondarySaleInput

# Set high precision for calculations
getcontext().prec = 100


class TestPrimaryYieldAccuracy:
    """اختبارات دقة حاسبة العائد الأساسي"""

    def test_basic_calculation_accuracy(self):
        """اختبار دقة الحساب الأساسي"""
        inputs = PrimaryYieldInput(
            face_value=100000.0, yield_rate=25.0, tenor=364, tax_rate=20.0
        )

        result = calculate_primary_yield(inputs)

        # التحقق من العلاقات الرياضية الأساسية
        assert result.purchase_price + result.gross_return == pytest.approx(
            100000.0, rel=1e-10
        )
        assert result.net_return == pytest.approx(
            result.gross_return - result.tax_amount, rel=1e-10
        )
        assert result.tax_amount == pytest.approx(result.gross_return * 0.20, rel=1e-10)
        assert result.total_payout == pytest.approx(100000.0, rel=1e-10)

        # التحقق من نسبة الربح الحقيقية
        expected_profit_percentage = (result.net_return / result.purchase_price) * 100
        assert result.real_profit_percentage == pytest.approx(
            expected_profit_percentage, rel=1e-10
        )

    def test_edge_cases_accuracy(self):
        """اختبار دقة الحالات الحدية"""
        test_cases = [
            # عائد منخفض جداً
            {"face_value": 100000.0, "yield_rate": 1.0, "tenor": 91, "tax_rate": 15.0},
            # عائد مرتفع جداً
            {
                "face_value": 100000.0,
                "yield_rate": 50.0,
                "tenor": 364,
                "tax_rate": 25.0,
            },
            # أجل قصير
            {"face_value": 50000.0, "yield_rate": 20.0, "tenor": 91, "tax_rate": 20.0},
            # أجل طويل
            {
                "face_value": 200000.0,
                "yield_rate": 30.0,
                "tenor": 364,
                "tax_rate": 15.0,
            },
            # ضريبة صفرية
            {"face_value": 100000.0, "yield_rate": 25.0, "tenor": 182, "tax_rate": 0.0},
            # ضريبة كاملة
            {
                "face_value": 100000.0,
                "yield_rate": 25.0,
                "tenor": 182,
                "tax_rate": 100.0,
            },
        ]

        for case in test_cases:
            inputs = PrimaryYieldInput(**case)
            result = calculate_primary_yield(inputs)

            # التحقق من صحة النتائج
            assert result.purchase_price > 0
            assert result.gross_return >= 0
            assert result.tax_amount >= 0
            assert (
                result.net_return >= 0
                if case["tax_rate"] < 100
                else result.net_return == 0
            )
            assert result.total_payout == case["face_value"]

    def test_precision_accuracy(self):
        """اختبار دقة الحسابات العشرية"""
        # استخدام قيم دقيقة جداً
        inputs = PrimaryYieldInput(
            face_value=123456.789, yield_rate=22.345, tenor=273, tax_rate=18.567
        )

        result = calculate_primary_yield(inputs)

        # التحقق من عدم فقدان الدقة
        assert result.purchase_price + result.gross_return == pytest.approx(
            123456.789, rel=1e-15
        )
        assert result.net_return == pytest.approx(
            result.gross_return - result.tax_amount, rel=1e-15
        )

    def test_reference_cases_accuracy(self):
        """اختبار دقة الحالات المرجعية المعروفة"""
        # حالة مرجعية معروفة النتائج
        inputs = PrimaryYieldInput(
            face_value=100000.0, yield_rate=25.0, tenor=364, tax_rate=20.0
        )

        result = calculate_primary_yield(inputs)

        # النتائج المتوقعة (محسوبة يدوياً)
        # سعر الشراء = 100000 / (1 + 25/100 * 364/365) = 80043.86
        expected_purchase_price = 80043.86  # محسوب بدقة
        expected_gross_return = 19956.14
        expected_tax_amount = 3991.23
        expected_net_return = 15964.91

        # التحقق من النتائج مع نسبة تفاوت صغيرة جداً
        assert (
            abs(result.purchase_price - expected_purchase_price)
            / expected_purchase_price
            < 0.01
        )
        assert (
            abs(result.gross_return - expected_gross_return) / expected_gross_return
            < 0.01
        )
        assert abs(result.tax_amount - expected_tax_amount) / expected_tax_amount < 0.01
        assert abs(result.net_return - expected_net_return) / expected_net_return < 0.01


class TestSecondarySaleAccuracy:
    """اختبارات دقة حاسبة البيع الثانوي"""

    def test_profit_scenario_accuracy(self):
        """اختبار دقة حساب الربح في البيع الثانوي"""
        inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=20.0,  # عائد أقل = سعر أعلى
            tax_rate=20.0,
        )

        result = analyze_secondary_sale(inputs)

        # التحقق من صحة النتائج
        assert result.sale_price > result.original_purchase_price
        assert result.gross_profit > 0
        assert result.tax_amount > 0
        assert result.net_profit == pytest.approx(
            result.gross_profit - result.tax_amount, rel=1e-10
        )
        assert result.period_yield > 0

    def test_loss_scenario_accuracy(self):
        """اختبار دقة حساب الخسارة في البيع الثانوي"""
        # استخدام عائد ثانوي أعلى بكثير لضمان الخسارة
        inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=50.0,  # عائد أعلى بكثير = سعر أقل
            tax_rate=20.0,
        )

        result = analyze_secondary_sale(inputs)

        # التحقق من صحة النتائج
        assert result.sale_price < result.original_purchase_price
        assert result.gross_profit < 0
        assert result.tax_amount == 0  # لا ضريبة على الخسارة
        assert result.net_profit == result.gross_profit
        assert result.period_yield < 0

    def test_edge_cases_secondary_accuracy(self):
        """اختبار دقة الحالات الحدية للبيع الثانوي"""
        test_cases = [
            # بيع مبكر جداً
            {"holding_days": 1, "secondary_yield": 15.0},
            # بيع قبل يوم واحد
            {"holding_days": 363, "secondary_yield": 25.0},
            # عائد ثانوي منخفض جداً
            {"holding_days": 180, "secondary_yield": 1.0},
            # عائد ثانوي مرتفع جداً
            {"holding_days": 180, "secondary_yield": 50.0},
        ]

        base_input = {
            "face_value": 100000.0,
            "original_yield": 25.0,
            "original_tenor": 364,
            "tax_rate": 20.0,
        }

        for case in test_cases:
            inputs = SecondarySaleInput(**{**base_input, **case})
            result = analyze_secondary_sale(inputs)

            # التحقق من صحة النتائج
            assert result.original_purchase_price > 0
            assert result.sale_price > 0
            assert result.tax_amount >= 0
            assert result.net_profit == pytest.approx(
                result.gross_profit - result.tax_amount, rel=1e-10
            )

    def test_tax_calculation_accuracy(self):
        """اختبار دقة حساب الضريبة في البيع الثانوي"""
        # حالة بدون ضريبة (خسارة)
        inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=60.0,  # عائد أعلى بكثير لضمان الخسارة
            tax_rate=20.0,
        )
        result = analyze_secondary_sale(inputs)
        assert result.tax_amount == 0

        # حالة بضريبة صفرية
        inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=20.0,
            tax_rate=0.0,
        )
        result = analyze_secondary_sale(inputs)
        assert result.tax_amount == 0
        assert result.net_profit == result.gross_profit

    def test_period_yield_accuracy(self):
        """اختبار دقة حساب عائد الفترة"""
        inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=20.0,
            tax_rate=20.0,
        )

        result = analyze_secondary_sale(inputs)

        # حساب عائد الفترة يدوياً للتحقق
        expected_period_yield = (
            result.net_profit / result.original_purchase_price
        ) * 100
        assert result.period_yield == pytest.approx(expected_period_yield, rel=1e-10)


class TestMathematicalConsistency:
    """اختبارات اتساق الحسابات الرياضية"""

    def test_formula_consistency(self):
        """اختبار اتساق المعادلات الرياضية"""
        # اختبار معادلة سعر الشراء
        face_value = 100000.0
        yield_rate = 25.0
        tenor = 364

        # الحساب اليدوي
        manual_denominator = 1 + (yield_rate / 100 * tenor / 365)
        manual_purchase_price = face_value / manual_denominator

        # الحساب بواسطة التطبيق
        inputs = PrimaryYieldInput(
            face_value=face_value, yield_rate=yield_rate, tenor=tenor, tax_rate=20.0
        )
        result = calculate_primary_yield(inputs)

        # التحقق من تطابق النتائج
        assert result.purchase_price == pytest.approx(manual_purchase_price, rel=1e-10)

    def test_round_trip_consistency(self):
        """اختبار اتساق الحسابات ذهاباً وإياباً"""
        # حساب العائد الأساسي
        primary_inputs = PrimaryYieldInput(
            face_value=100000.0, yield_rate=25.0, tenor=364, tax_rate=20.0
        )
        primary_result = calculate_primary_yield(primary_inputs)

        # استخدام النتائج في البيع الثانوي
        secondary_inputs = SecondarySaleInput(
            face_value=100000.0,
            original_yield=25.0,
            original_tenor=364,
            holding_days=180,
            secondary_yield=25.0,  # نفس العائد
            tax_rate=20.0,
        )
        secondary_result = analyze_secondary_sale(secondary_inputs)

        # التحقق من الاتساق - يجب أن يكون سعر الشراء الأصلي متطابق
        assert secondary_result.original_purchase_price == pytest.approx(
            primary_result.purchase_price, rel=1e-10
        )

    def test_decimal_precision_consistency(self):
        """اختبار اتساق الدقة العشرية"""
        # اختبار مع قيم دقيقة جداً
        inputs = PrimaryYieldInput(
            face_value=123456.789012345,
            yield_rate=22.345678901,
            tenor=273,
            tax_rate=18.567890123,
        )

        result = calculate_primary_yield(inputs)

        # التحقق من عدم فقدان الدقة في العمليات المتسلسلة
        calculated_total = result.purchase_price + result.gross_return
        assert calculated_total == pytest.approx(123456.789012345, rel=1e-15)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
