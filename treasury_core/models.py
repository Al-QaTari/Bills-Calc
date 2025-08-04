"""
Data models for the Treasury Bills Calculator application.
نماذج البيانات لتطبيق حاسبة أذون الخزانة.
"""

from pydantic import BaseModel, Field, PositiveFloat, NonNegativeFloat, field_validator


class PrimaryYieldInput(BaseModel):
    """
    Model representing inputs for the primary yield calculator.
    نموذج يمثل المدخلات اللازمة لحاسبة العائد الأساسية.
    Pydantic will automatically validate these conditions.
    """

    face_value: PositiveFloat  # Must be a positive decimal number
    yield_rate: PositiveFloat
    tenor: int = Field(gt=0)  # Must be an integer greater than zero
    tax_rate: float = Field(ge=0, le=100)  # Must be a number between 0 and 100


class PrimaryYieldResult(BaseModel):
    """
    Model representing outputs from the primary yield calculator.
    نموذج يمثل مخرجات حاسبة العائد الأساسية.
    """

    purchase_price: PositiveFloat
    gross_return: NonNegativeFloat  # Can be zero
    tax_amount: NonNegativeFloat
    net_return: float  # Net profit can be negative in rare cases
    total_payout: PositiveFloat
    real_profit_percentage: float


class SecondarySaleInput(BaseModel):
    """
    Model representing inputs for the secondary sale calculator.
    نموذج يمثل المدخلات اللازمة لحاسبة البيع الثانوي.
    """

    face_value: PositiveFloat
    original_yield: PositiveFloat
    original_tenor: int = Field(gt=0)
    holding_days: int = Field(gt=0)
    secondary_yield: PositiveFloat
    tax_rate: float = Field(ge=0, le=100)

    @field_validator("holding_days")
    def validate_holding_days(cls, value, info):
        """
        Validate that holding days is within valid range.

        Args:
            value: The holding days value
            info: Validation info containing other field values

        Returns:
            Validated holding days value

        Raises:
            ValueError: If holding days is invalid
        """
        tenor = info.data.get("original_tenor")
        if tenor is not None and (value <= 0 or value >= tenor):
            raise ValueError(
                "أيام الاحتفاظ يجب أن تكون أكبر من صفر وأقل من أجل الإذن الأصلي."
            )
        return value


class SecondarySaleResult(BaseModel):
    """
    Model representing outputs from the secondary sale calculator.
    نموذج يمثل مخرجات حاسبة البيع الثانوي.
    """

    original_purchase_price: PositiveFloat
    sale_price: PositiveFloat
    gross_profit: float  # Gross profit can be negative (loss)
    tax_amount: NonNegativeFloat
    net_profit: float
    period_yield: float
