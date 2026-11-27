"""
كشف الفجوات في جلسات العطاءات.

القاعدة الفعلية: كل أجل ليه جلسة واحدة في الأسبوع، والإصدار دايمًا يوم الثلاثاء.
- 91 و273 يوم: جلسة يوم الأحد (قبل الإصدار بيومين).
- 182 و364 يوم: جلسة يوم الخميس (قبل الإصدار بخمسة أيام).
الجلسة ممكن تتأجل أيام قليلة بسبب إجازة (الخميس يبقى الأحد مثلًا) وفي البيانات
فعلًا جلسات يوم الاثنين وجلسات مخزّنة بتاريخ الإصدار نفسه (الثلاثاء).

الكاشف القديم كان بيعدّ كل يوم اثنين وثلاثاء وأربعاء بين جلستين "يوم مفقود"،
مع إن مفيش عطاء في الأيام دي أصلًا، فكان بيطلع عشرات الفجوات الكاذبة.

الكاشف ده بيربط كل جلسة بأسبوع الإصدار (أول ثلاثاء في نفس اليوم أو بعده)، ويقارن
كل أجل بأسابيعه هو بس. الفجوة الحقيقية = أسبوع إصدار ناقص بين أسبوعين موجودين.
تأجيل الجلسة داخل نفس الأسبوع مش فجوة.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tenors import normalize_tenor

DATE_FORMAT = "%d/%m/%Y"
WEEK_DAYS = 7
TUESDAY = 1
# عمود تاريخ الإصدار الرسمي (نص DD/MM/YYYY، يقبل NULL للصفوف القديمة لحد ما تتملي)
ISSUE_DATE_COLUMN = "issue_date"

# الأجل الأساسي -> يوم الجلسة المعتاد (Python weekday: الاثنين=0 ... الأحد=6)
SESSION_WEEKDAY_BY_TENOR = {91: 6, 273: 6, 182: 3, 364: 3}
# عدد الأيام بين يوم الجلسة وتاريخ الإصدار (الثلاثاء) في الوضع المعتاد
ISSUE_OFFSET_DAYS_BY_TENOR = {91: 2, 273: 2, 182: 5, 364: 5}


def parse_session_date(value: Any) -> Optional[date]:
    """حوّل نص بصيغة DD/MM/YYYY لتاريخ، أو None لو غير صالح."""
    try:
        return datetime.strptime(str(value).strip(), DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None


def issue_tuesday(session: date) -> date:
    """أول ثلاثاء في نفس اليوم أو بعده: هو يوم إصدار العطاء المرتبط بالجلسة."""
    return session + timedelta(days=(TUESDAY - session.weekday()) % WEEK_DAYS)


def find_session_gaps(rows: Iterable[Tuple[Any, ...]]) -> List[Dict[str, Any]]:
    """
    rows: أزواج (الأجل، تاريخ الجلسة DD/MM/YYYY) أو ثلاثيات بتاريخ الإصدار الرسمي
    كعنصر تالت. لو تاريخ الإصدار موجود وصالح (ثلاثاء) بيتحدد بيه الأسبوع مباشرة، ولو
    فاضي بيتحسب من تاريخ الجلسة زي الأول."
    الناتج: قايمة فجوات بنفس الشكل القديم (start_date, end_date, missing_dates,
    gap_length) مع tenor_family لتوضيح الأجل المتأثر. missing_dates هي تواريخ الجلسة
    المتوقعة (الأحد أو الخميس) للأسابيع الناقصة.
    الآجال غير الأساسية (غير 91/182/273/364 بعد التوحيد) بتتجاهل.
    """
    weeks_by_weekday: Dict[int, Dict[date, date]] = defaultdict(dict)
    for row in rows:
        tenor, session = row[0], row[1]
        stated_issue = parse_session_date(row[2]) if len(row) > 2 else None
        nominal = normalize_tenor(tenor)
        if nominal not in SESSION_WEEKDAY_BY_TENOR:
            continue
        parsed = parse_session_date(session)
        if parsed is None:
            continue
        family = SESSION_WEEKDAY_BY_TENOR[nominal]
        if stated_issue is not None and stated_issue.weekday() == TUESDAY:
            week = stated_issue
        else:
            week = issue_tuesday(parsed)
        # نحتفظ بأقدم تاريخ جلسة في الأسبوع، للتقرير فقط
        known = weeks_by_weekday[family].get(week)
        if known is None or parsed < known:
            weeks_by_weekday[family][week] = parsed

    family_names = {6: "91/273", 3: "182/364"}
    offsets = {
        6: ISSUE_OFFSET_DAYS_BY_TENOR[91],
        3: ISSUE_OFFSET_DAYS_BY_TENOR[182],
    }
    gaps: List[Dict[str, Any]] = []
    for family in sorted(weeks_by_weekday):
        weeks = sorted(weeks_by_weekday[family])
        for previous, current in zip(weeks, weeks[1:]):
            diff = (current - previous).days
            if diff <= WEEK_DAYS:
                continue
            missing_weeks = [
                previous + timedelta(days=WEEK_DAYS * (i + 1))
                for i in range(diff // WEEK_DAYS - 1)
            ]
            missing = [w - timedelta(days=offsets[family]) for w in missing_weeks]
            gaps.append(
                {
                    "start_date": weeks_by_weekday[family][previous].strftime(
                        DATE_FORMAT
                    ),
                    "end_date": weeks_by_weekday[family][current].strftime(DATE_FORMAT),
                    "missing_dates": [d.strftime(DATE_FORMAT) for d in missing],
                    "gap_length": len(missing),
                    "tenor_family": family_names[family],
                }
            )
    gaps.sort(key=lambda g: parse_session_date(g["start_date"]))
    return gaps
