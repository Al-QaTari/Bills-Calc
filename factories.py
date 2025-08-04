"""
Factory classes for creating input models in the Treasury Bills Calculator.
مصانع لإنشاء نماذج المدخلات في حاسبة أذون الخزانة.
"""

from treasury_core.models import PrimaryYieldInput, SecondarySaleInput


class InputModelFactory:
    """
    Factory for creating input models.
    مصنع لإنشاء نماذج المدخلات.
    """

    @staticmethod
    def create_primary_yield_input(form_data: dict) -> PrimaryYieldInput:
        """
        Create a primary yield input model from form data.

        Args:
            form_data: Dictionary containing form data

        Returns:
            PrimaryYieldInput instance
        """
        return PrimaryYieldInput(
            face_value=form_data.get("face_value"),
            yield_rate=form_data.get("yield_rate"),
            tenor=form_data.get("tenor"),
            tax_rate=form_data.get("tax_rate"),
        )

    @staticmethod
    def create_secondary_sale_input(form_data: dict) -> SecondarySaleInput:
        """
        Create a secondary sale input model from form data.

        Args:
            form_data: Dictionary containing form data

        Returns:
            SecondarySaleInput instance
        """
        return SecondarySaleInput(
            face_value=form_data.get("face_value"),
            original_yield=form_data.get("original_yield"),
            original_tenor=form_data.get("original_tenor"),
            holding_days=form_data.get("holding_days"),
            secondary_yield=form_data.get("secondary_yield"),
            tax_rate=form_data.get("tax_rate"),
        )
