"""
مقارنة عائد أذونك بعطاءات السوق، وملخصات بسيطة لمنحنى العائد.

القاعدة: لكل أذن بناخد آخر عطاء لنفس الأجل بتاريخ قبل أو يوم الإصدار، بشرط الفرق
بين تاريخ العطاء وتاريخ الإصدار مايزيدش عن MAX_GAP_DAYS. غير كده: "مفيش عطاء مقارن".
دي مقارنة تقديرية: السعر الفعلي ممكن يختلف حسب طريقة الشراء.
"""

from datetime import date
from typing import Any, Dict, Optional

import pandas as pd

import constants as C
from tenors import normalize_tenor

MAX_GAP_DAYS = 21
# الإصدار الثلاثاء والجلسة الأحد أو الخميس (ومعها تأجيل الإجازات): فرق أكبر من 6 أيام
# معناه إن عطاء أسبوع الإصدار نفسه غالبًا مش مسجل، فالعطاء المعروض أقدم منه.
NORMAL_MAX_GAP_DAYS = 6
SAME_TOLERANCE_PP = 0.05  # أقل من كده نقول "زي السوق"


def pct(v: float) -> str:
    """رقم بنسبة مئوية جوه bdi عشان علامة % تفضل بعد الرقم في النص العربي (للعرض كـ HTML)."""
    return f"<bdi dir='ltr'>{v:.2f}%</bdi>"


def prepare_sessions(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """جدول نضيف: tenor, yield, session (تاريخ العطاء كـ datetime). التاريخ نص dd/mm/yyyy."""
    cols = ["tenor", "yield", "session"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    need = {C.TENOR_COLUMN_NAME, C.YIELD_COLUMN_NAME, C.SESSION_DATE_COLUMN_NAME}
    if not need.issubset(df.columns):
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(
        {
            "tenor": pd.to_numeric(df[C.TENOR_COLUMN_NAME], errors="coerce"),
            "yield": pd.to_numeric(df[C.YIELD_COLUMN_NAME], errors="coerce"),
            "session": pd.to_datetime(
                df[C.SESSION_DATE_COLUMN_NAME], dayfirst=True, errors="coerce"
            ),
        }
    ).dropna()
    out["tenor"] = out["tenor"].astype(int)
    return out.sort_values("session").reset_index(drop=True)


def compare_bill(
    sessions: pd.DataFrame,
    tenor_days: int,
    yield_rate: float,
    issue_date: date,
    max_gap_days: int = MAX_GAP_DAYS,
) -> Dict[str, Any]:
    none = {"status": "none"}
    if sessions is None or sessions.empty:
        return none
    t = normalize_tenor(tenor_days)
    issue = pd.Timestamp(issue_date)
    sub = sessions[(sessions["tenor"] == t) & (sessions["session"] <= issue)]
    if sub.empty:
        return none
    row = sub.iloc[-1]
    gap = (issue - row["session"]).days
    if gap > max_gap_days:
        return none
    diff = round(float(yield_rate) - float(row["yield"]), 3)
    status = (
        "same"
        if abs(diff) < SAME_TOLERANCE_PP
        else ("better" if diff > 0 else "weaker")
    )
    return {
        "status": status,
        "diff": diff,
        "market_yield": float(row["yield"]),
        "session": row["session"].date(),
        "gap_days": gap,
    }


def bill_line(cmp: Dict[str, Any]) -> str:
    s = cmp["status"]
    if s == "none":
        return "مفيش عطاء مقارن"
    d = abs(cmp["diff"])
    base = (
        f"آخر عطاء قبل الإصدار: <bdi dir='ltr'>{cmp['session'].strftime('%d/%m/%Y')}</bdi>"
        f" بعائد {pct(cmp['market_yield'])}"
    )
    if cmp["gap_days"] > NORMAL_MAX_GAP_DAYS:
        base += (
            f"<br>⚠️ العطاء قبل الإصدار بـ {cmp['gap_days']} يوم، "
            "ممكن عطاء أسبوع الإصدار مش مسجل بعد"
        )
    if s == "same":
        return f"زي السوق وقتها (تقدير)<br>{base}"
    word = "أحسن" if s == "better" else "أضعف"
    return (
        f"{word} من السوق وقتها بـ <bdi dir='ltr'>{d:.2f}</bdi> نقطة (تقدير)<br>{base}"
    )


def latest_by_tenor(sessions: pd.DataFrame, window_days: int = 120) -> pd.DataFrame:
    """آخر عائد لكل أجل، من الآجال اللي نزلت في آخر window_days قبل أحدث عطاء."""
    if sessions is None or sessions.empty:
        return pd.DataFrame(columns=["tenor", "yield", "session"])
    newest = sessions["session"].max()
    recent = sessions[sessions["session"] >= newest - pd.Timedelta(days=window_days)]
    last = recent.sort_values("session").groupby("tenor", as_index=False).tail(1)
    return last.sort_values("tenor").reset_index(drop=True)


def curve_takeaway(latest: pd.DataFrame) -> str:
    """جملة واحدة بسيطة عن أعلى عائد حاليًا وشكل المنحنى."""
    if latest is None or latest.empty:
        return "مفيش بيانات كفاية نقول منها حاجة."
    top = latest.loc[latest["yield"].idxmax()]
    msg = f"العائد الأعلى حاليًا في أجل {int(top['tenor'])} يوم: {pct(top['yield'])}."
    if len(latest) >= 2:
        short, long_ = latest.iloc[0], latest.iloc[-1]
        if short["yield"] > long_["yield"] + 0.05:
            msg += " الآجال القصيرة بتدفع أكتر من الطويلة دلوقتي."
        elif long_["yield"] > short["yield"] + 0.05:
            msg += " كل ما الأجل بيطول العائد بيزيد."
        else:
            msg += " العائد قريب في كل الآجال."
    return msg


def period_stats(filtered: pd.DataFrame) -> pd.DataFrame:
    """لكل أجل: المتوسط، الأقل، الأعلى، آخر عائد في الفترة المختارة."""
    if filtered is None or filtered.empty:
        return pd.DataFrame()
    rows = []
    for tenor, g in filtered.sort_values("session").groupby("tenor"):
        rows.append(
            {
                "tenor": int(tenor),
                "avg": round(float(g["yield"].mean()), 2),
                "min": round(float(g["yield"].min()), 2),
                "max": round(float(g["yield"].max()), 2),
                "last": round(float(g["yield"].iloc[-1]), 2),
                "n": int(len(g)),
            }
        )
    return pd.DataFrame(rows).sort_values("tenor").reset_index(drop=True)


def stats_takeaway(stats: pd.DataFrame) -> str:
    if stats is None or stats.empty:
        return "مفيش بيانات في الفترة دي."
    best = stats.loc[stats["avg"].idxmax()]
    msg = f"في الفترة دي، أعلى متوسط عائد كان لأجل {int(best['tenor'])} يوم ({pct(best['avg'])})."
    diffs = (stats["last"] - stats["avg"]).round(2)
    below = [int(t) for t, d in zip(stats["tenor"], diffs) if d <= -0.5]
    above = [int(t) for t, d in zip(stats["tenor"], diffs) if d >= 0.5]
    if below:
        msg += (
            " آخر عائد أقل من المتوسط في: " + "، ".join(f"{t} يوم" for t in below) + "."
        )
    if above:
        msg += (
            " آخر عائد أعلى من المتوسط في: "
            + "، ".join(f"{t} يوم" for t in above)
            + "."
        )
    return msg
