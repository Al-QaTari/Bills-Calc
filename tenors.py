"""
أدوات الآجال: بتخلي التطبيق يتعامل مع اللي البنك المركزي بينشره من غير تعديل يدوي.

الحقيقة اللي اتأكدنا منها من صفحة البنك المركزي وبيانات القاعدة: رقم الأجل في جدول
النتائج هو عدد الأيام بين الإصدار والاستحقاق، فأذن السنة بيظهر أحيانًا 364 وأحيانًا
357 أو 336 حسب تاريخ الإصدار. هو نفس الأذن. عشان كده:

1) normalize_tenor: أي عدد أيام قريب (في حدود TOLERANCE_DAYS) من أجل أساسي
   (91/182/273/364) يتحول للأجل الأساسي.
2) أي أجل بعيد عن كل الآجال الأساسية (أجل جديد فعلاً) يفضل كما هو ويظهر تلقائيًا.
3) active_tenors: الآجال "الحالية" هي اللي ليها جلسة في آخر ACTIVE_WINDOW_DAYS يوم
   قبل أحدث جلسة في القاعدة. أجل بطل ينزل بيختفي لوحده، وأجل جديد بيظهر لوحده.
"""

from typing import Iterable, List, Optional

import pandas as pd

NOMINAL_TENORS = [91, 182, 273, 364]
TOLERANCE_DAYS = 35
ACTIVE_WINDOW_DAYS = 120
ACTUAL_DAYS_COL = "actual_days"


def normalize_tenor(days) -> Optional[int]:
    """حوّل عدد الأيام لأقرب أجل أساسي لو داخل التسامح، وإلا أرجعه كما هو."""
    try:
        d = int(round(float(days)))
    except (TypeError, ValueError):
        return None
    nearest = min(NOMINAL_TENORS, key=lambda n: abs(n - d))
    return nearest if abs(nearest - d) <= TOLERANCE_DAYS else d


def normalize_tenor_column(
    df: pd.DataFrame,
    tenor_col: str = "tenor",
    session_col: Optional[str] = "session_date",
) -> pd.DataFrame:
    """طبّق normalize_tenor على عمود الأجل وشيل التكرار (نفس الأجل ونفس الجلسة)."""
    if df is None or df.empty or tenor_col not in df.columns:
        return df
    out = df.copy()
    # عدد الأيام الفعلي بيتحفظ: الحسابات بتستخدمه، والتوحيد للعرض والتجميع بس
    if ACTUAL_DAYS_COL not in out.columns:
        out[ACTUAL_DAYS_COL] = out[tenor_col]
    out[tenor_col] = out[tenor_col].map(normalize_tenor)
    out = out.dropna(subset=[tenor_col])
    out[tenor_col] = out[tenor_col].astype(int)
    if session_col and session_col in out.columns:
        out = out.drop_duplicates(subset=[tenor_col, session_col], keep="first")
    return out


def _session_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, dayfirst=True, errors="coerce")


def latest_active_rows(
    df: pd.DataFrame,
    tenor_col: str = "tenor",
    session_col: str = "session_date",
    window_days: int = ACTIVE_WINDOW_DAYS,
) -> pd.DataFrame:
    """
    لكل أجل (بعد التوحيد) خد أحدث جلسة، واسقط الآجال اللي آخر جلسة ليها أقدم من
    window_days قبل أحدث جلسة في الجدول. الترتيب تصاعدي بالأجل.
    """
    if df is None or df.empty:
        return df
    work = normalize_tenor_column(df, tenor_col, session_col)
    work["_dt"] = _session_dt(work[session_col])
    work = work.dropna(subset=["_dt"])
    if work.empty:
        return work.drop(columns=["_dt"])
    work = work.sort_values("_dt", ascending=False).drop_duplicates(
        subset=[tenor_col], keep="first"
    )
    newest = work["_dt"].max()
    work = work[work["_dt"] >= newest - pd.DateOffset(days=int(window_days))]
    return work.sort_values(tenor_col).drop(columns=["_dt"]).reset_index(drop=True)


def active_tenors(
    df: Optional[pd.DataFrame],
    fallback: Iterable[int] = tuple(NOMINAL_TENORS),
    tenor_col: str = "tenor",
    session_col: str = "session_date",
) -> List[int]:
    """قائمة الآجال الحالية من البيانات، أو fallback لو مفيش بيانات."""
    if df is None or df.empty or tenor_col not in df.columns:
        return sorted(int(t) for t in fallback)
    if session_col in df.columns:
        rows = latest_active_rows(df, tenor_col, session_col)
        if rows is not None and not rows.empty:
            return sorted(int(t) for t in rows[tenor_col].tolist())
    return sorted(
        {t for t in (normalize_tenor(x) for x in df[tenor_col].unique()) if t}
    )


def months_label(days: int) -> str:
    """وصف الأجل بالأشهر للعناوين (91 -> 3 أشهر، 364 -> 12 شهر)."""
    m = max(1, round(days / 30.4375))
    if m == 1:
        return "شهر"
    if m == 2:
        return "شهرين"
    return f"{m} أشهر" if m <= 10 else f"{m} شهر"


SUNDAY_NOMINALS = (91, 273)


def auction_day_groups(tenors: Iterable[int]):
    """قسّم الآجال لعطاء الخميس (الباقي) وعطاء الأحد (91 و273)."""
    ts = sorted(int(t) for t in tenors)
    sunday = [t for t in ts if t in SUNDAY_NOMINALS]
    thursday = [t for t in ts if t not in SUNDAY_NOMINALS]
    return thursday, sunday


def group_label(tenors: Iterable[int]) -> str:
    """عنوان مجموعة آجال: آجال (6 أشهر و 12 شهر)."""
    parts = [months_label(t) for t in sorted(tenors)]
    return "آجال (" + " و ".join(parts) + ")"


def calc_days(tenor: int, df: Optional[pd.DataFrame]) -> int:
    """عدد الأيام الفعلي المستخدم في الحساب لأجل معروض (مثلاً 364 معروض وآخر جلسة كانت 357 يوم)."""
    try:
        if df is not None and ACTUAL_DAYS_COL in df.columns and not df.empty:
            rows = df[df["tenor"] == tenor]
            if not rows.empty:
                return int(rows[ACTUAL_DAYS_COL].iloc[0])
    except Exception:
        pass
    return int(tenor)
