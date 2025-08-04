"""
Calculation functions for Treasury Bills yield and secondary sale analysis.
دوال الحساب لعوائد أذون الخزانة وتحليل البيع الثانوي.
"""

import logging
import constants as C
import decimal
from .models import (
    PrimaryYieldInput,
    PrimaryYieldResult,
    SecondarySaleInput,
    SecondarySaleResult,
)
from decimal import Decimal, getcontext

# Initialize decimal precision to be very high to prevent any rounding
getcontext().prec = 100

logger = logging.getLogger(__name__)


def calculate_primary_yield(
    inputs: PrimaryYieldInput,
) -> PrimaryYieldResult:
    """
    Calculate investment returns on Treasury Bills when purchased from the primary market.
    يحسب عوائد الاستثمار في أذون الخزانة عند الشراء من السوق الأولي.

    Args:
        inputs: Input parameters for the calculation

    Returns:
        PrimaryYieldResult containing calculation results

    Raises:
        ValueError: If inputs are invalid or calculation fails
    """
    try:
        logger.debug(f"بدء حساب العائد الأساسي بالبيانات: {inputs.model_dump()}")

        # Convert inputs to Decimal for high precision calculations
        try:
            face_value = Decimal(str(inputs.face_value))
            yield_rate = Decimal(str(inputs.yield_rate))
            tenor = Decimal(str(inputs.tenor))
            tax_rate = Decimal(str(inputs.tax_rate))
        except decimal.ConversionSyntax as e:
            # When conversion error occurs, throw a clear error instead of crashing
            error_msg = "المدخلات الرقمية غير صالحة. لا يمكن ترك الحقول فارغة."
            logger.error(f"{error_msg} | {e}")
            raise ValueError(error_msg)

        # Validate basic values
        if yield_rate <= 0:
            raise ValueError("يجب أن يكون معدل العائد رقمًا موجبًا")
        if tenor <= 0:
            raise ValueError("يجب أن تكون مدة الإذن أكبر من الصفر")

        # Calculate purchase price
        denominator = Decimal("1") + (
            yield_rate / Decimal("100") * tenor / Decimal(str(C.DAYS_IN_YEAR))
        )

        if denominator <= 0:
            raise ValueError("قيمة المقام غير صالحة في حساب سعر الشراء")

        # Normal calculation - always use the actual formula
        purchase_price = face_value / denominator
        gross_return = face_value - purchase_price
        tax_amount = gross_return * (tax_rate / Decimal("100"))
        net_return = gross_return - tax_amount

        real_profit_percentage = (
            (net_return / purchase_price) * Decimal("100")
            if purchase_price > Decimal("0")
            else Decimal("0")
        )

        result = PrimaryYieldResult(
            purchase_price=purchase_price,
            gross_return=gross_return,
            tax_amount=tax_amount,
            net_return=net_return,
            total_payout=face_value,
            real_profit_percentage=real_profit_percentage,
        )

        logger.info(f"تم حساب العائد الأساسي بنجاح. صافي الربح: {result.net_return}")
        return result

    except ZeroDivisionError:
        error_msg = "خطأ في الحساب: قسمة على صفر"
        logger.error(error_msg)
        raise ValueError(error_msg)
    except Exception as e:
        error_msg = f"خطأ غير متوقع في حساب العائد الأساسي: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg)


def analyze_secondary_sale(
    inputs: SecondarySaleInput,
) -> SecondarySaleResult:
    """
    Analyze secondary market sale of Treasury Bills.
    تحليل بيع أذون الخزانة في السوق الثانوي.

    Args:
        inputs: Input parameters for the secondary sale analysis

    Returns:
        SecondarySaleResult containing analysis results

    Raises:
        ValueError: If inputs are invalid or calculation fails
    """
    try:
        logger.debug(f"بدء تحليل البيع الثانوي بالبيانات: {inputs.model_dump()}")

        # Convert inputs to Decimal for high precision calculations
        try:
            face_value = Decimal(str(inputs.face_value))
            original_yield = Decimal(str(inputs.original_yield))
            original_tenor = Decimal(str(inputs.original_tenor))
            holding_days = Decimal(str(inputs.holding_days))
            secondary_yield = Decimal(str(inputs.secondary_yield))
            tax_rate = Decimal(str(inputs.tax_rate))
        except decimal.ConversionSyntax as e:
            error_msg = "المدخلات الرقمية غير صالحة. لا يمكن ترك الحقول فارغة."
            logger.error(f"{error_msg} | {e}")
            raise ValueError(error_msg)

        # Validate inputs
        if holding_days >= original_tenor:
            raise ValueError("أيام الاحتفاظ يجب أن تكون أقل من أجل الإذن الأصلي")

        # Calculate original purchase price
        original_denominator = Decimal("1") + (
            original_yield
            / Decimal("100")
            * original_tenor
            / Decimal(str(C.DAYS_IN_YEAR))
        )
        original_purchase_price = face_value / original_denominator

        # Calculate remaining days
        remaining_days = original_tenor - holding_days

        # Calculate secondary sale price
        secondary_denominator = Decimal("1") + (
            secondary_yield
            / Decimal("100")
            * remaining_days
            / Decimal(str(C.DAYS_IN_YEAR))
        )
        sale_price = face_value / secondary_denominator

        # Calculate profits and taxes
        gross_profit = sale_price - original_purchase_price
        tax_amount = max(gross_profit * (tax_rate / Decimal("100")), Decimal("0"))
        net_profit = gross_profit - tax_amount

        # Calculate period yield
        period_yield = (
            (net_profit / original_purchase_price) * Decimal("100")
            if original_purchase_price > Decimal("0")
            else Decimal("0")
        )

        result = SecondarySaleResult(
            original_purchase_price=original_purchase_price,
            sale_price=sale_price,
            gross_profit=gross_profit,
            tax_amount=tax_amount,
            net_profit=net_profit,
            period_yield=period_yield,
        )

        logger.info(f"تم تحليل البيع الثانوي بنجاح. صافي الربح: {result.net_profit}")
        return result

    except ZeroDivisionError:
        error_msg = "خطأ في الحساب: قسمة على صفر"
        logger.error(error_msg)
        raise ValueError(error_msg)
    except Exception as e:
        error_msg = f"خطأ غير متوقع في تحليل البيع الثانوي: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg)
