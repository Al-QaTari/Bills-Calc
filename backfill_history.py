"""
ملء الجلسات الناقصة في جدول العوائد من صفحة "البيانات التاريخية" الرسمية للبنك المركزي.

ليه الأداة دي موجودة: التحديث الدوري بيسحب آخر جلستين بس من صفحة النتائج، فأي جلسة
فاتت (السكرابر وقع، أو الموقع كان واقف) ما بتتعوّضش أبدًا. الصفحة التاريخية فيها كل
العطاءات لأي فترة، فبنقارنها بالقاعدة ونضيف الناقص بس.

بيشتغل أوتوماتيك في workflow التحديث (الأحد والخميس) بعد سحب آخر النتائج، بـ --apply.
تشغيله من غير --apply تجربة (dry-run): بيطبع اللي هيتضاف ومش بيكتب أي حاجة.

قواعد الأمان (مهمة):
- الكتابة بس مع --apply، وبـ INSERT ... ON CONFLICT DO NOTHING جوه معاملة واحدة.
  مفيش UPDATE ولا DELETE، فالصفوف الموجودة مستحيل تتغيّر.
- الهدف الافتراضي PostgreSQL (POSTGRES_URI): لو المتغير مش موجود بيقف، مفيش بديل صامت.
  --target sqlite:المسار بيضيف نسخة SQLite المحفوظة في المستودع (data/cbe_historical_data.db)
  عشان تفضل زي PostgreSQL. كل هدف مستقل: فشل واحد مايوقفش التاني.
- لو الصفحة الرسمية واقفة أو مش بترد: تحذير في اللوج، مفيش كتابة، والـ workflow يكمل.
- صف التاريخ الرسمي بيعرض تاريخ الإصدار (الثلاثاء) مش تاريخ الجلسة. تاريخ الجلسة
  بيتحسب (الأحد لـ 91/273، الخميس لـ 182/364) ولو طلع يوم تاني (إجازة) الصف مش
  بيتضاف ويتسجّل "يحتاج مراجعة".
- لو العائد في القاعدة مختلف عن الرسمي لنفس الأسبوع: تعارض، بيتسجّل ومش بيتلمس.
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import constants as C
from gaps import (
    DATE_FORMAT,
    ISSUE_OFFSET_DAYS_BY_TENOR,
    SESSION_WEEKDAY_BY_TENOR,
    parse_session_date,
)
from tenors import normalize_tenor
from timeutil import cairo_now

HISTORY_URL = "https://www.cbe.org.eg/ar/auctions/egp-t-bills/historical-data"
EXPECTED_COLUMNS = 10
# ترتيب أعمدة الجدول الرسمي: المدة، ISIN، الإصدار، الاستحقاق، المطلوب، المقدم،
# المقبول، أدنى عائد، أعلى عائد، متوسط العائد المرجح (للمقبول)
COL_TENOR, COL_ISIN, COL_ISSUE, COL_MATURITY, COL_YIELD = 0, 1, 2, 3, 9

MIN_YIELD_EXCLUSIVE = 0.0
MAX_YIELD = 60.0
MIN_TENOR_DAYS = 7
MAX_TENOR_DAYS = 800
YIELD_TOLERANCE = 0.0005
# أقصى فرق بين تاريخ الجلسة وتاريخ الإصدار: الأحد (2) والخميس (5) وتأجيل الإجازات (6)
MAX_SESSION_TO_ISSUE_DAYS = 6
MAX_REJECTED_FRACTION = 0.10
MIN_MATCH_RATIO = 0.80
DEFAULT_MAX_INSERT = 50


class FetchError(RuntimeError):
    """الصفحة الرسمية مش متاحة دلوقتي (مش خطأ في الكود، وهنحاول في التشغيل الجاي)."""


@dataclass(frozen=True)
class OfficialAuction:
    tenor: int
    isin: str
    issue: date
    maturity: date
    yield_pct: float


@dataclass
class Plan:
    to_insert: List[Dict[str, Any]] = field(default_factory=list)
    already_present: int = 0
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    needs_review: List[Dict[str, Any]] = field(default_factory=list)
    skipped_old: int = 0
    skipped_future: int = 0


# ---------------------------------------------------------------------------
# قراءة الجدول الرسمي والتحقق منه
# ---------------------------------------------------------------------------
def _parse_number(text: str) -> float:
    return float(str(text).replace(",", "").strip())


def parse_official_rows(
    raw_rows: Iterable[Sequence[str]],
) -> Tuple[List[OfficialAuction], List[Tuple[Any, str]]]:
    """حوّل صفوف الجدول النصية لعطاءات، وارفض أي صف مش سليم مع ذكر السبب."""
    accepted: Dict[Tuple[int, date], OfficialAuction] = {}
    rejected: List[Tuple[Any, str]] = []
    for raw in raw_rows:
        row = [str(cell).strip() for cell in raw]
        if len(row) != EXPECTED_COLUMNS:
            rejected.append((row, "عدد الأعمدة غير متوقع"))
            continue
        try:
            tenor = int(row[COL_TENOR])
            issue = parse_session_date(row[COL_ISSUE])
            maturity = parse_session_date(row[COL_MATURITY])
            yield_pct = _parse_number(row[COL_YIELD])
        except ValueError:
            rejected.append((row, "قيمة غير رقمية"))
            continue
        if issue is None or maturity is None:
            rejected.append((row, "تاريخ غير صالح"))
            continue
        if not MIN_TENOR_DAYS <= tenor <= MAX_TENOR_DAYS:
            rejected.append((row, "أجل غير معقول"))
            continue
        if (maturity - issue).days != tenor:
            rejected.append((row, "الأجل لا يطابق الفرق بين الإصدار والاستحقاق"))
            continue
        if not MIN_YIELD_EXCLUSIVE < yield_pct < MAX_YIELD:
            rejected.append((row, "عائد غير معقول"))
            continue
        auction = OfficialAuction(
            tenor=tenor,
            isin=row[COL_ISIN],
            issue=issue,
            maturity=maturity,
            yield_pct=round(yield_pct, 3),
        )
        key = (tenor, issue)
        previous = accepted.get(key)
        if previous is not None and previous.yield_pct != auction.yield_pct:
            rejected.append((row, "نفس الأجل والإصدار بعائدين مختلفين"))
            accepted.pop(key)
            continue
        accepted[key] = auction
    ordered = sorted(accepted.values(), key=lambda a: (a.issue, a.tenor))
    return ordered, rejected


def extract_rows_from_html(html: str) -> List[List[str]]:
    """استخرج صفوف الجداول اللي أول خلية فيها رقم (المدة) من HTML الصفحة."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    rows: List[List[str]] = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) == EXPECTED_COLUMNS and cells[0].isdigit():
            rows.append(cells)
    return rows


async def fetch_official_rows(from_date: date, to_date: date) -> List[List[str]]:
    """افتح الصفحة الرسمية واطلب الفترة من النموذج (نفس خطوات المستخدم) واقرأ الجداول."""
    try:
        return await _fetch_official_rows(from_date, to_date)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc


async def _fetch_official_rows(from_date: date, to_date: date) -> List[List[str]]:
    from playwright.async_api import async_playwright

    from cbe_scraper import ensure_chromium_installed

    await asyncio.to_thread(ensure_chromium_installed)
    timeout_ms = int(getattr(C, "SCRAPER_TIMEOUT_SECONDS", 60)) * 1000
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=getattr(C, "USER_AGENT", None), locale="ar-EG"
            )
            page = await context.new_page()
            response = await page.goto(
                HISTORY_URL, timeout=timeout_ms, wait_until="networkidle"
            )
            if not response or not response.ok:
                raise RuntimeError(
                    f"فشل تحميل الصفحة التاريخية: {response.status if response else 'لا استجابة'}"
                )
            await page.wait_for_selector("#fromDate", state="attached")
            await page.evaluate(
                """([fromValue, toValue]) => {
                    const from = document.getElementById('fromDate');
                    if (from._flatpickr) { from._flatpickr.setDate(fromValue, true, 'd/m/Y'); }
                    else { from.value = fromValue; }
                    document.getElementById('toDate').value = toValue;
                    document.getElementById('btnsubmit').click();
                }""",
                [from_date.strftime(DATE_FORMAT), to_date.strftime(DATE_FORMAT)],
            )
            await page.wait_for_selector("table td", timeout=timeout_ms)
            await asyncio.sleep(2)
            return extract_rows_from_html(await page.content())
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# المقارنة مع القاعدة
# ---------------------------------------------------------------------------
def infer_session_date(tenor: int, issue: date) -> Tuple[Optional[date], str]:
    """تاريخ الجلسة المتوقع = الإصدار ناقص يومين (الأحد) أو خمسة (الخميس)."""
    nominal = normalize_tenor(tenor)
    if nominal not in SESSION_WEEKDAY_BY_TENOR:
        return None, "أجل غير أساسي"
    session = issue - timedelta(days=ISSUE_OFFSET_DAYS_BY_TENOR[nominal])
    if session.weekday() != SESSION_WEEKDAY_BY_TENOR[nominal]:
        return None, "يوم الجلسة المتوقع مختلف عن المعتاد (غالبًا إجازة)"
    return session, ""


def build_plan(
    official: Sequence[OfficialAuction],
    db_rows: Sequence[Tuple[int, str, float]],
    since: date,
    today: date,
) -> Plan:
    """قارن العطاءات الرسمية بصفوف القاعدة (الأجل، تاريخ الجلسة، العائد)."""
    db_by_nominal: Dict[int, List[Tuple[date, float, str]]] = {}
    db_keys = set()
    for tenor, session_text, yield_pct in db_rows:
        parsed = parse_session_date(session_text)
        if parsed is None:
            continue
        nominal = normalize_tenor(tenor)
        db_by_nominal.setdefault(nominal, []).append((parsed, yield_pct, session_text))
        db_keys.add((int(tenor), session_text))

    plan = Plan()
    for auction in official:
        if auction.issue <= since:
            plan.skipped_old += 1
            continue
        nominal = normalize_tenor(auction.tenor)
        window = [
            (session, y)
            for session, y, _ in db_by_nominal.get(nominal, [])
            if 0 <= (auction.issue - session).days <= MAX_SESSION_TO_ISSUE_DAYS
        ]
        if any(abs(y - auction.yield_pct) <= YIELD_TOLERANCE for _, y in window):
            plan.already_present += 1
            continue
        info = {
            "tenor": auction.tenor,
            "issue": auction.issue.strftime(DATE_FORMAT),
            "yield": auction.yield_pct,
        }
        if window:
            info["db_session"] = window[0][0].strftime(DATE_FORMAT)
            info["db_yield"] = window[0][1]
            plan.conflicts.append(info)
            continue
        session, reason = infer_session_date(auction.tenor, auction.issue)
        if session is None:
            info["reason"] = reason
            plan.needs_review.append(info)
            continue
        if session > today:
            plan.skipped_future += 1
            continue
        session_text = session.strftime(DATE_FORMAT)
        if (auction.tenor, session_text) in db_keys:
            info["reason"] = "تاريخ الجلسة المتوقع موجود بالفعل لنفس الأجل"
            plan.needs_review.append(info)
            continue
        info["session_date"] = session_text
        plan.to_insert.append(info)
    return plan


def check_plan_is_sane(plan: Plan, parsed_count: int, rejected_count: int) -> None:
    """وقف التنفيذ لو الصفحة أو القاعدة شكلهم غلط (بدل ما نكتب حاجة غلط)."""
    if parsed_count == 0:
        raise RuntimeError("الصفحة الرسمية ما رجّعتش أي عطاء سليم")
    total_rows = parsed_count + rejected_count
    if rejected_count / total_rows > MAX_REJECTED_FRACTION:
        raise RuntimeError(
            f"صفوف مرفوضة كتير ({rejected_count} من {total_rows}): شكل الصفحة اتغيّر على الأغلب"
        )
    compared = (
        plan.already_present
        + len(plan.to_insert)
        + len(plan.conflicts)
        + len(plan.needs_review)
        + plan.skipped_future
    )
    if compared == 0:
        raise RuntimeError("لا توجد عطاءات داخل الفترة للمقارنة")
    if plan.already_present / compared < MIN_MATCH_RATIO:
        raise RuntimeError(
            "نسبة التطابق مع القاعدة منخفضة "
            f"({plan.already_present} من {compared}): القاعدة أو الصفحة مش زي المتوقع"
        )


# ---------------------------------------------------------------------------
# القاعدة
# ---------------------------------------------------------------------------
def make_engine(target: str):
    """target: "postgres" (من POSTGRES_URI) أو "sqlite:المسار". مفيش بديل صامت."""
    from sqlalchemy import create_engine

    if target.startswith("sqlite:"):
        path = target[len("sqlite:") :]
        if not path or not os.path.isfile(path):
            raise RuntimeError(f"ملف SQLite غير موجود: {path or '(فاضي)'}")
        return create_engine(f"sqlite:///{path}"), "sqlite"
    if target != "postgres":
        raise RuntimeError(f"هدف غير معروف: {target}")
    uri = os.environ.get("POSTGRES_URI")
    if not uri:
        raise RuntimeError("POSTGRES_URI غير موجود: مفيش بديل محلي صامت.")
    uri = uri.replace("postgres://", "postgresql+psycopg2://", 1)
    engine = create_engine(
        uri, pool_pre_ping=True, connect_args={"connect_timeout": 10}
    )
    return engine, "postgres"


def load_db_rows(conn) -> List[Tuple[int, str, float]]:
    from sqlalchemy import text

    result = conn.execute(
        text(
            f'SELECT "{C.TENOR_COLUMN_NAME}", "{C.SESSION_DATE_COLUMN_NAME}", '
            f'"{C.YIELD_COLUMN_NAME}" FROM "{C.TABLE_NAME}"'
        )
    )
    return [(int(t), str(s), float(y)) for t, s, y in result.fetchall()]


def insert_missing(conn, kind: str, rows: Sequence[Dict[str, Any]]) -> int:
    """INSERT ... ON CONFLICT DO NOTHING لكل صف. يرجّع عدد الصفوف اللي اتكتبت فعلًا."""
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    scrape_value: Any = (
        now.strftime("%Y-%m-%d %H:%M:%S+00:00") if kind == "sqlite" else now
    )
    statement = text(
        f'INSERT INTO "{C.TABLE_NAME}" '
        f'("{C.TENOR_COLUMN_NAME}", "{C.YIELD_COLUMN_NAME}", '
        f'"{C.SESSION_DATE_COLUMN_NAME}", "{C.DATE_COLUMN_NAME}") '
        "VALUES (:tenor, :yield, :session_date, :scrape_date) "
        f'ON CONFLICT ("{C.TENOR_COLUMN_NAME}", "{C.SESSION_DATE_COLUMN_NAME}") DO NOTHING'
    )
    inserted = 0
    for row in rows:
        result = conn.execute(
            statement,
            {
                "tenor": int(row["tenor"]),
                "yield": float(row["yield"]),
                "session_date": row["session_date"],
                "scrape_date": scrape_value,
            },
        )
        inserted += max(result.rowcount, 0)
    return inserted


def verify_after_apply(
    before: Sequence[Tuple[int, str, float]],
    after: Sequence[Tuple[int, str, float]],
    inserted_rows: Sequence[Dict[str, Any]],
) -> List[str]:
    """تأكد إن الصفوف القديمة زي ما هي وإن كل صف جديد موجود بعائده."""
    problems: List[str] = []
    after_map = {(t, s): y for t, s, y in after}
    for t, s, y in before:
        if (t, s) not in after_map:
            problems.append(f"صف قديم اختفى: {t} {s}")
        elif abs(after_map[(t, s)] - y) > 1e-9:
            problems.append(f"صف قديم اتغيّر: {t} {s}")
    for row in inserted_rows:
        key = (int(row["tenor"]), row["session_date"])
        if key not in after_map:
            problems.append(f"صف جديد مش موجود: {key}")
        elif abs(after_map[key] - float(row["yield"])) > 0.0005:
            problems.append(f"عائد الصف الجديد مختلف: {key}")
    if len(after) != len(before) + len(inserted_rows):
        problems.append(
            f"عدد الصفوف بعد التنفيذ {len(after)} مش {len(before)} + {len(inserted_rows)}"
        )
    return problems


# ---------------------------------------------------------------------------
# التقرير والتشغيل
# ---------------------------------------------------------------------------
def format_report(plan: Plan, since: date, apply: bool, label: str = "") -> str:
    lines = [
        f"[{label}] المقارنة من بعد {since.strftime(DATE_FORMAT)}",
        f"موجود بالفعل في القاعدة: {plan.already_present}",
        f"ناقص وهيتضاف: {len(plan.to_insert)}",
        f"تعارض في العائد (مش هيتلمس): {len(plan.conflicts)}",
        f"يحتاج مراجعة (مش هيتضاف): {len(plan.needs_review)}",
        f"قبل بداية الفترة (اتخطّى): {plan.skipped_old}",
    ]
    if plan.skipped_future:
        lines.append(f"جلسات مستقبلية (اتخطّت): {plan.skipped_future}")
    for row in plan.to_insert:
        lines.append(
            f"  + أجل {row['tenor']} | جلسة {row['session_date']} "
            f"(إصدار {row['issue']}) | عائد {row['yield']}%"
        )
    for row in plan.conflicts:
        lines.append(
            f"  ! تعارض: أجل {row['tenor']} إصدار {row['issue']} الرسمي {row['yield']}% "
            f"والقاعدة {row['db_yield']}% (جلسة {row['db_session']})"
        )
    for row in plan.needs_review:
        lines.append(
            f"  ? مراجعة: أجل {row['tenor']} إصدار {row['issue']} عائد {row['yield']}% "
            f"({row['reason']})"
        )
    lines.append(
        "وضع التنفيذ: هيتضاف الصف الناقص بس (INSERT فقط، مفيش تعديل ولا حذف)."
        if apply
        else "تجربة فقط (dry-run): لم يتم تعديل أي شيء. أضف --apply للتنفيذ."
    )
    return "\n".join(lines)


def _annotate(level: str, message: str) -> None:
    """في GitHub Actions بتظهر كتحذير ظاهر في ملخص التشغيل."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{message}")


@dataclass
class Target:
    name: str
    engine: Any
    kind: str
    db_rows: List[Tuple[int, str, float]]
    since: date


def _open_target(spec: str, since_arg: Optional[str]) -> Target:
    engine, kind = make_engine(spec)
    try:
        with engine.connect() as conn:
            db_rows = load_db_rows(conn)
        if not db_rows:
            raise RuntimeError("جدول العوائد فاضي: ده مش المكان المناسب للملء التاريخي")
        db_dates = [d for d in (parse_session_date(s) for _, s, _ in db_rows) if d]
        if not db_dates:
            raise RuntimeError("لا توجد تواريخ جلسات صالحة في الجدول")
        since = parse_session_date(since_arg) if since_arg else min(db_dates)
        if since is None:
            raise RuntimeError("--since لازم تكون بصيغة DD/MM/YYYY")
        return Target(spec, engine, kind, db_rows, since)
    except Exception:
        engine.dispose()
        raise


def _process_target(
    target: Target,
    official: Sequence[OfficialAuction],
    rejected_count: int,
    today: date,
    apply: bool,
    max_insert: int,
) -> int:
    plan = build_plan(official, target.db_rows, target.since, today)
    print(format_report(plan, target.since, apply=apply, label=target.name))
    check_plan_is_sane(plan, len(official), rejected_count)
    for row in plan.conflicts:
        _annotate(
            "warning",
            f"[{target.name}] تعارض عائد أجل {row['tenor']} إصدار {row['issue']}: "
            f"الرسمي {row['yield']}% والقاعدة {row['db_yield']}% (لم يتم تعديل شيء)",
        )
    for row in plan.needs_review:
        _annotate(
            "warning",
            f"[{target.name}] عطاء يحتاج مراجعة أجل {row['tenor']} إصدار {row['issue']}: {row['reason']}",
        )
    if not apply:
        return 0
    if not plan.to_insert:
        print(f"[{target.name}] لا يوجد ما يُضاف.")
        return 0
    if len(plan.to_insert) > max_insert:
        raise RuntimeError(
            f"عدد الصفوف الجديدة {len(plan.to_insert)} أكبر من الحد {max_insert}: لم يتم تنفيذ شيء"
        )
    with target.engine.connect() as conn:
        with conn.begin():
            inserted = insert_missing(conn, target.kind, plan.to_insert)
    with target.engine.connect() as conn:
        after = load_db_rows(conn)
    problems = verify_after_apply(target.db_rows, after, plan.to_insert)
    if problems or inserted != len(plan.to_insert):
        for problem in problems:
            print(f"[{target.name}] خطأ تحقق: {problem}")
        print(f"[{target.name}] اتضاف {inserted} من {len(plan.to_insert)}")
        return 1
    print(f"[{target.name}] تم إضافة {inserted} صف والتحقق منها.")
    return 0


def run(args: argparse.Namespace) -> int:
    specs = args.target or ["postgres"]
    targets: List[Target] = []
    failed = 0
    for spec in specs:
        try:
            targets.append(_open_target(spec, args.since))
        except Exception as exc:  # noqa: BLE001
            failed = 1
            print(f"[{spec}] تعذر فتح الهدف: {exc}", file=sys.stderr)
            _annotate("warning", f"الملء التاريخي: تعذر فتح {spec}")
    if not targets:
        return 2
    try:
        today = cairo_now().date()
        if args.official_json:
            import json

            with open(args.official_json, encoding="utf-8") as handle:
                raw_rows = json.load(handle)
        else:
            try:
                raw_rows = asyncio.run(
                    fetch_official_rows(min(t.since for t in targets), today)
                )
            except FetchError as exc:
                print(
                    f"الصفحة التاريخية الرسمية غير متاحة دلوقتي، مفيش تعديل. هنحاول في التشغيل الجاي. ({exc})"
                )
                _annotate(
                    "warning", "الصفحة التاريخية الرسمية غير متاحة: لم يتم ملء أي جلسة"
                )
                return 0
        official, rejected = parse_official_rows(raw_rows)
        for target in targets:
            try:
                failed = max(
                    failed,
                    _process_target(
                        target,
                        official,
                        len(rejected),
                        today,
                        args.apply,
                        args.max_insert,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                failed = 2
                print(f"[{target.name}] توقف الملء: {exc}", file=sys.stderr)
                _annotate("warning", f"الملء التاريخي توقف في {target.name}: {exc}")
        return failed
    finally:
        for target in targets:
            target.engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ملء جلسات العوائد الناقصة من الصفحة الرسمية (تجربة افتراضيًا)."
    )
    parser.add_argument("--apply", action="store_true", help="نفّذ الكتابة فعلًا")
    parser.add_argument(
        "--target",
        action="append",
        help='"postgres" (الافتراضي) أو "sqlite:المسار". ممكن تتكرر.',
    )
    parser.add_argument(
        "--since",
        help="ابدأ بعد التاريخ ده (DD/MM/YYYY). الافتراضي: أول جلسة في كل قاعدة",
    )
    parser.add_argument(
        "--official-json", help="ملف JSON بصفوف الصفحة الرسمية (للاختبار بدون إنترنت)"
    )
    parser.add_argument("--max-insert", type=int, default=DEFAULT_MAX_INSERT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ توقف الملء التاريخي: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
