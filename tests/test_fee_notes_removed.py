"""Fee captions were removed on request; the estimate markers must stay.

Removed: the caption under the primary calculator's net-profit card, the caption
under the secondary-sale results, and the long caption above the ledger form.
Kept: "(تقدير)" labels, field tooltips, the "رسوم مؤكدة؟" column and the
unconfirmed-fees caption above the table.
"""

import ast
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


def _src(name):
    return (UI / name).read_text(encoding="utf-8")


def test_removed_captions_are_gone():
    assert "الرسوم التقديرية: شراء" not in _src("primary_yield_calculator.py")
    assert "الأرقام هنا قبل رسوم البنك" not in _src("secondary_sale_calculator.py")
    assert "كل حاجة بتتحسب لوحدها" not in _src("portfolio.py")
    assert "جدول رسوم أمين الحفظ ولا تشمل" not in _src("portfolio.py")


def test_estimate_markers_kept():
    primary = _src("primary_yield_calculator.py")
    assert "صافي الربح بعد الرسوم (تقدير)" in primary
    assert "fees['total']" in primary
    portfolio = _src("portfolio.py")
    for text in (
        "رسم الاستحقاق (تقدير)",
        "رسم الحفظ (تقدير)",
        "رسم الشراء (تقدير)",
        "رسوم مؤكدة؟",
        "لا (تقدير)",
        "الرسوم في الصفوف غير المؤكدة تقدير",
        "بعد الضريبة والرسوم التقديرية",
    ):
        assert text in portfolio, text


def test_ledger_form_still_has_fee_expander_and_buy_button():
    portfolio = _src("portfolio.py")
    assert "تعديل التواريخ والرسوم (اختياري)" in portfolio
    assert "اشتريت هذا الأذن" in portfolio


def test_ui_files_still_parse():
    for name in (
        "portfolio.py",
        "primary_yield_calculator.py",
        "secondary_sale_calculator.py",
    ):
        ast.parse(_src(name))
