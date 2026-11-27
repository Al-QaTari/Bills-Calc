"""
دفتر محفظة أذون الخزانة (الحسابات + التخزين).

قواعد الخصوصية:
- التخزين في PostgreSQL فقط (POSTGRES_URI). مفيش بديل محلي: لو القاعدة مش متاحة،
  الدفتر يتقفل ويظهر خطأ، ومفيش بيانات بتتكتب في ملف.
- كل قراءة وكتابة تعدي على LedgerStore، والواجهة بتتأكد من كلمة المرور قبل ما تنده عليه.

قواعد الأرقام:
- التواريخ الرسمية (الإصدار والاستحقاق) منفصلة عن تواريخ كشف الحساب الفعلية.
- الربح المتوقع (تقدير) منفصل عن الربح المحقق (من أرقام كشف الحساب).
- الرسوم غير المعروفة قيمتها None (مش صفر) وبتتعلم "غير مؤكدة".
"""

import os
import logging
import weakref
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)

import constants as C

logger = logging.getLogger(__name__)


class LedgerUnavailable(RuntimeError):
    """الدفتر مقفول: القاعدة مش متاحة أو الإعدادات ناقصة."""


# ---------------------------------------------------------------------------
# الحسابات
# ---------------------------------------------------------------------------
def estimate_redemption_fee(face_value: float) -> float:
    """رسم الاستحقاق التقديري: 1 في الألف بحد أقصى 1000 جنيه."""
    return round(
        min(face_value * C.LEDGER_REDEMPTION_FEE_RATE, C.LEDGER_REDEMPTION_FEE_CAP), 2
    )


def estimate_purchase_fee(face_value: float) -> float:
    """رسم الشراء التقديري: 2.5 لكل 100 ألف (0.0025%) بحد أقصى 1000 جنيه (جدول رسوم أمين الحفظ)."""
    return round(
        min(face_value * C.LEDGER_PURCHASE_FEE_RATE, C.LEDGER_PURCHASE_FEE_CAP), 2
    )


def estimate_custody_fee(face_value: float, days: int) -> float:
    """رسم الحفظ التقديري: 0.02% سنويًا موزعة على أيام الاحتفاظ."""
    return round(
        face_value * C.LEDGER_CUSTODY_ANNUAL_RATE * days / C.DAYS_IN_YEAR,
        2,
    )


def maturity_from_issue(issue_date: date, days: int) -> date:
    """الاستحقاق = تاريخ الإصدار + عدد أيام الأجل."""
    return issue_date + timedelta(days=int(days))


def known_fees_total(row: Dict[str, Any]) -> float:
    return sum(
        float(row[k] or 0)
        for k in ("purchase_fee", "redemption_fee", "custody_fee")
        if row.get(k) is not None
    )


# القيم اللي بتتأكد من الكشف كل واحدة لوحدها: مفتاح -> (عمود التخزين، الاسم)
CONFIRM_FIELDS = {
    "purchase_debit_date": ("actual_purchase_debit_date", "تاريخ خصم الشراء"),
    "purchase_debit": ("actual_purchase_debit", "المبلغ المخصوم عند الشراء"),
    "credit_date": ("actual_credit_date", "تاريخ نزول القيمة الاسمية"),
    "proceeds": ("actual_proceeds", "المبلغ المستلم"),
    "tax": ("actual_tax_debit", "الضريبة المخصومة"),
    "fees": ("actual_fees", "إجمالي الرسوم المخصومة"),
}
# الربح المحقق مايتحسبش إلا لما كل دول يتأكدوا (تاريخ خصم الشراء معلومة بس)
REQUIRED_FOR_PROFIT = ("purchase_debit", "credit_date", "proceeds", "tax", "fees")


def confirmed_fields(row: Dict[str, Any]) -> set:
    """
    القيم المؤكدة من الكشف. صف قديم (من غير العمود) كل قيمة فيه متسجلة كانت متأكدة،
    والمبلغ المستلم فيه هو القيمة الاسمية افتراضيًا.
    """
    raw = row.get("confirmed_fields")
    if raw is None:
        got = {k for k, (col, _) in CONFIRM_FIELDS.items() if row.get(col) is not None}
        got.add("proceeds")
        return got
    return {
        k
        for k in str(raw).split(",")
        if k in CONFIRM_FIELDS and (row.get(CONFIRM_FIELDS[k][0]) is not None)
    }


def confirm_field_update(row: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    """التحديث اللي بيتكتب لما قيمة واحدة تتأكد: القيمة نفسها + إضافتها للمؤكدين."""
    col = CONFIRM_FIELDS[key][0]
    cf = confirmed_fields(row) | {key}
    out = {col: value, "confirmed_fields": ",".join(sorted(cf))}
    if key == "fees":
        out["fees_confirmed"] = True
    return out


def field_status(row: Dict[str, Any], key: str, current: Any) -> str:
    """confirmed | changed (القيمة المكتوبة غير المؤكدة المحفوظة) | estimate."""
    if key not in confirmed_fields(row):
        return "estimate"
    saved = row.get(CONFIRM_FIELDS[key][0])
    if isinstance(saved, float) or isinstance(current, float):
        same = abs(float(saved) - float(current)) < 0.005
    else:
        same = saved == current
    return "confirmed" if same else "changed"


def all_confirmed(row: Dict[str, Any]) -> bool:
    return set(REQUIRED_FOR_PROFIT) <= confirmed_fields(row)


def fees_complete(row: Dict[str, Any]) -> bool:
    """كل الرسوم معروفة ومأكدة من الكشف؟"""
    return (
        "fees" in confirmed_fields(row)
        if row.get("confirmed_fields") is not None
        else bool(row.get("fees_confirmed"))
    )


def is_sold(row: Dict[str, Any]) -> bool:
    return row.get("sold_on") is not None


def expected_net(row: Dict[str, Any]) -> float:
    """
    الربح الصافي المتوقع (تقدير).
    للأذن المحتفظ بيه للاستحقاق: العائد الإجمالي - الضريبة - الرسوم المعروفة.
    للأذن المباع في السوق الثانوي: صافي البيع (بعد الضريبة) - رسم الشراء والحفظ المعروفين
    (رسم الاستحقاق مش بينطبق).
    """
    if is_sold(row) and row.get("sale_net") is not None:
        fees = sum(
            float(row[k] or 0)
            for k in ("purchase_fee", "custody_fee")
            if row.get(k) is not None
        )
        return float(row["sale_net"]) - fees
    return float(row["gross_return"]) - float(row["tax_amount"]) - known_fees_total(row)


def proceeds(row: Dict[str, Any]) -> float:
    """المبلغ المستلم فعلاً: اللي في الكشف لو متسجل، وإلا القيمة الاسمية."""
    v = row.get("actual_proceeds")
    return float(v) if v is not None else float(row["face_value"])


def expected_timeline(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    الحركات المتوقعة على الحساب (تقدير تلقائي، والتواريخ الفعلية من الكشف):
    خصم سعر الشراء عند الإصدار، نزول القيمة الاسمية عند الاستحقاق، خصم الضريبة،
    وبعدها بيوم خصم مصاريف الأوراق المالية (زي كشفك).
    """
    mat = row["maturity_date"]
    out = [
        {
            "date": row["issue_date"],
            "item": "خصم سعر الشراء",
            "amount": -round(float(row["purchase_price"]), 2),
        },
        {
            "date": mat,
            "item": "نزول القيمة الاسمية",
            "amount": float(row["face_value"]),
        },
        {
            "date": mat,
            "item": "خصم الضريبة",
            "amount": -round(float(row["tax_amount"]), 2),
        },
    ]
    if row.get("redemption_fee") is not None:
        out.append(
            {
                "date": mat + timedelta(days=1),
                "item": "خصم مصاريف أوراق مالية",
                "amount": -float(row["redemption_fee"]),
            }
        )
    return out


def is_settled(row: Dict[str, Any]) -> bool:
    """نزلت الفلوس: تاريخ النزول والضريبة متأكدين من الكشف."""
    return (
        row.get("actual_credit_date") is not None
        and row.get("actual_tax_debit") is not None
        and {"credit_date", "tax"} <= confirmed_fields(row)
    )


def realized_net(row: Dict[str, Any]) -> Optional[float]:
    """
    الربح المحقق من أرقام كشف الحساب فقط:
    المبلغ الاسمي المستلم - المبلغ المدفوع فعلاً - الضريبة الفعلية - الرسوم الفعلية.
    بيرجع None لو الأرقام الفعلية ناقصة.
    """
    if not is_settled(row) or not all_confirmed(row):
        return None
    paid = row.get("actual_purchase_debit")
    if paid is None:
        return None
    fees = row.get("actual_fees")
    if fees is None:
        return None
    return proceeds(row) - float(paid) - float(row["actual_tax_debit"]) - float(fees)


# ---------------------------------------------------------------------------
# التخزين
# ---------------------------------------------------------------------------
metadata = MetaData()

purchases = Table(
    C.LEDGER_TABLE_NAME,
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_on", Date, nullable=False),
    # بيانات الشراء (لقطة وقت الحفظ)
    Column("face_value", Float, nullable=False),
    Column("yield_rate", Float, nullable=False),
    Column("tenor_days", Integer, nullable=False),
    Column("tax_rate", Float, nullable=False),
    Column("purchase_price", Float, nullable=False),
    Column("gross_return", Float, nullable=False),
    Column("tax_amount", Float, nullable=False),
    # التواريخ الرسمية
    Column("issue_date", Date, nullable=False),
    Column("maturity_date", Date, nullable=False),
    # رسوم: None = غير معروف
    Column("purchase_fee", Float, nullable=True),
    Column("redemption_fee", Float, nullable=True),
    Column("custody_fee", Float, nullable=True),
    Column("fees_confirmed", Boolean, nullable=False, default=False),
    # أرقام وتواريخ كشف الحساب الفعلية (None لحد ما تتسجل)
    Column("actual_purchase_debit_date", Date, nullable=True),
    Column("actual_purchase_debit", Float, nullable=True),
    Column("actual_credit_date", Date, nullable=True),
    Column("actual_tax_debit", Float, nullable=True),
    Column("actual_fees", Float, nullable=True),
    Column("note", String, nullable=True),
    # بيع في السوق الثانوي (تقدير لحد ما يتأكد من الكشف)
    Column("sold_on", Date, nullable=True),
    Column("sale_price", Float, nullable=True),
    Column("sale_tax", Float, nullable=True),
    Column("sale_net", Float, nullable=True),
    Column("actual_proceeds", Float, nullable=True),
    # تاريخ إرسال تنبيه الاستحقاق (مرة واحدة لكل أذن). NULL = لسه ما اتبعتش.
    Column("alerted_on", Date, nullable=True),
    # القيم اللي اتأكدت من كشف الحساب واحدة واحدة (مفاتيح مفصولة بفاصلة). NULL = صف قديم.
    Column("confirmed_fields", String, nullable=True),
)

_LEDGER_COLS = [c.name for c in purchases.columns]


_ENGINES: Dict[str, Any] = {}
_ENSURED: "weakref.WeakSet" = weakref.WeakSet()


def _get_engine():
    """محرك PostgreSQL فقط (من غير بديل) بمهل قصيرة عشان الواجهة ماتعلقش لو القاعدة بطيئة."""
    uri = os.environ.get("POSTGRES_URI")
    if not uri:
        raise LedgerUnavailable("POSTGRES_URI غير مضبوط")
    uri = uri.replace("postgres://", "postgresql+psycopg2://", 1)
    try:
        eng = _ENGINES.get(uri)
        if eng is None:
            from sqlalchemy import create_engine

            eng = create_engine(
                uri,
                pool_size=2,
                max_overflow=0,
                pool_timeout=C.LEDGER_DB_POOL_TIMEOUT,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={
                    "connect_timeout": C.LEDGER_DB_CONNECT_TIMEOUT,
                    "options": f"-c statement_timeout={C.LEDGER_DB_STATEMENT_TIMEOUT_MS}",
                },
            )
            _ENGINES[uri] = eng
        return eng
    except Exception as e:  # noqa: BLE001
        raise LedgerUnavailable(
            f"تعذر الاتصال بقاعدة البيانات: {type(e).__name__}"
        ) from e


class LedgerStore:
    def __init__(self, engine=None):
        # engine بيتمرر في الاختبارات بس. في التشغيل العادي بيتجاب من PostgreSQL.
        self.engine = engine if engine is not None else _get_engine()
        try:
            if self.engine not in _ENSURED:  # مرة واحدة لكل محرك، مش مع كل rerun
                metadata.create_all(self.engine, tables=[purchases])
                self._ensure_columns()
                _ENSURED.add(self.engine)
        except Exception as e:  # noqa: BLE001
            raise LedgerUnavailable(
                f"تعذر تجهيز جدول الدفتر: {type(e).__name__}"
            ) from e

    def _ensure_columns(self) -> None:
        """جدول قديم ناقصه أعمدة جديدة: بنضيفها (مرة واحدة، من غير ما نلمس الصفوف)."""
        from sqlalchemy import inspect, text

        have = {c["name"] for c in inspect(self.engine).get_columns(purchases.name)}
        wanted = (("alerted_on", "DATE"), ("confirmed_fields", "VARCHAR"))
        for name, sql_type in wanted:
            if name not in have:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            f"ALTER TABLE {purchases.name} ADD COLUMN {name} {sql_type}"
                        )
                    )

    def mark_alerted(self, row_id: int, when: date) -> None:
        self.update_row(row_id, {"alerted_on": when})

    def add(self, data: Dict[str, Any]) -> int:
        values = {k: v for k, v in data.items() if k in _LEDGER_COLS and k != "id"}
        values.setdefault("confirmed_fields", "")  # صف جديد: ولا قيمة متأكدة لسه
        with self.engine.begin() as conn:
            res = conn.execute(insert(purchases).values(**values))
            return int(res.inserted_primary_key[0])

    def list_all(self) -> List[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(purchases).order_by(
                    purchases.c.issue_date.desc(), purchases.c.id.desc()
                )
            ).mappings()
            return [dict(r) for r in rows]

    def update_row(self, row_id: int, data: Dict[str, Any]) -> None:
        values = {k: v for k, v in data.items() if k in _LEDGER_COLS and k != "id"}
        with self.engine.begin() as conn:
            conn.execute(
                update(purchases).where(purchases.c.id == row_id).values(**values)
            )

    def delete_row(self, row_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(purchases).where(purchases.c.id == row_id))


@dataclass
class Summary:
    open_count: int
    open_face_total: float
    expected_net_open: float
    expected_net_by_year: Dict[int, float]  # حسب سنة الاستحقاق (تقدير)
    realized_net_by_year: Dict[int, float]  # حسب سنة نزول الفلوس (من الكشف فقط)
    realized_report_by_year: Dict[int, Dict[str, float]]  # تقرير السنة (من الكشف فقط)
    unsettled_past_maturity: int
    unconfirmed_fee_rows: int


def summarize(rows: List[Dict[str, Any]], today: date) -> Summary:
    open_rows = [r for r in rows if not is_settled(r)]
    exp_year: Dict[int, float] = {}
    real_year: Dict[int, float] = {}
    report: Dict[int, Dict[str, float]] = {}
    for r in rows:
        if not is_settled(r):
            y = period_date(r).year
            exp_year[y] = exp_year.get(y, 0.0) + expected_net(r)
        else:
            rn = realized_net(r)
            if rn is not None:
                y = period_date(r).year
                real_year[y] = real_year.get(y, 0.0) + rn
                d = report.setdefault(
                    y, {"count": 0, "gross": 0.0, "tax": 0.0, "fees": 0.0, "net": 0.0}
                )
                d["count"] += 1
                d["gross"] += proceeds(r) - float(r["actual_purchase_debit"])
                d["tax"] += float(r["actual_tax_debit"])
                d["fees"] += float(r["actual_fees"])
                d["net"] += rn
    return Summary(
        open_count=len(open_rows),
        open_face_total=sum(float(r["face_value"]) for r in open_rows),
        expected_net_open=sum(expected_net(r) for r in open_rows),
        expected_net_by_year=dict(sorted(exp_year.items())),
        realized_net_by_year=dict(sorted(real_year.items())),
        realized_report_by_year=dict(sorted(report.items())),
        unsettled_past_maturity=sum(1 for r in open_rows if r["maturity_date"] < today),
        unconfirmed_fee_rows=sum(1 for r in rows if not fees_complete(r)),
    )


@dataclass
class AnnualReport:
    year: int
    half: Optional[int]
    entered: List[Dict[str, Any]]  # الأذون اللي اتسجلت (إصدارها) في السنة
    realized_rows: List[Dict[str, Any]]  # اللي نزلت فلوسها في السنة (من الكشف)
    count: int
    gross: float
    tax: float
    fees: float
    net: float  # الصافي النهائي المحقق بعد الضرايب والرسوم
    open_from_year: List[Dict[str, Any]]  # اتسجلت في السنة ولسه مفتوحة (تقدير)
    open_expected_net: float
    realized_missing_numbers: int  # نزلت فلوسها بس أرقام الكشف ناقصة


def period_label(year: int, half: Optional[int]) -> str:
    if half == 1:
        return f"{year} H1"
    if half == 2:
        return f"{year} H2"
    return str(year)


def _in_period(d: date, year: int, half: Optional[int]) -> bool:
    if d.year != year:
        return False
    if half is None:
        return True
    return (d.month <= 6) if half == 1 else (d.month >= 7)


def period_date(row: Dict[str, Any]) -> date:
    """
    التاريخ اللي بيتحدد بيه تقرير الأذن: تاريخ الاستحقاق الرسمي.
    الأذن المباع في السوق الثانوي مفيش له استحقاق بيتقبض، فبيتحسب بتاريخ البيع.
    """
    return row["sold_on"] if is_sold(row) else row["maturity_date"]


def annual_report(
    rows: List[Dict[str, Any]], year: int, half: Optional[int] = None
) -> AnnualReport:
    """
    تقرير سنة (أو نصف سنة): الأذن بيتحسب في الفترة اللي فيها تاريخ استحقاقه (period_date).
    - half=1 (يناير-يونيو) أو half=2 (يوليو-ديسمبر) بنفس الأساس.
    - الربح المحقق من أرقام كشف الحساب بس. الأذن اللي استحقاقه في الفترة ولسه مفيش له
      أرقام كشف بيظهر منفصل كتقدير ومش بيدخل في الصافي المحقق.
    """
    entered = [r for r in rows if _in_period(period_date(r), year, half)]
    realized_rows = [
        r for r in entered if is_settled(r) and realized_net(r) is not None
    ]
    gross = sum(proceeds(r) - float(r["actual_purchase_debit"]) for r in realized_rows)
    tax = sum(float(r["actual_tax_debit"]) for r in realized_rows)
    fees = sum(float(r["actual_fees"]) for r in realized_rows)
    net = sum(realized_net(r) for r in realized_rows)
    open_rows = [r for r in entered if not is_settled(r)]
    missing = sum(1 for r in entered if is_settled(r) and realized_net(r) is None)
    return AnnualReport(
        year=year,
        half=half,
        entered=entered,
        realized_rows=realized_rows,
        count=len(realized_rows),
        gross=gross,
        tax=tax,
        fees=fees,
        net=net,
        open_from_year=open_rows,
        open_expected_net=sum(expected_net(r) for r in open_rows),
        realized_missing_numbers=missing,
    )


def fee_estimates(face_value: float, days: int) -> Dict[str, float]:
    """كل رسوم البنك التقديرية لأذن واحد (الشراء + الاستحقاق + الحفظ) ومجموعها."""
    pf = estimate_purchase_fee(face_value)
    rf = estimate_redemption_fee(face_value)
    cf = estimate_custody_fee(face_value, days)
    return {
        "purchase": pf,
        "redemption": rf,
        "custody": cf,
        "total": round(pf + rf + cf, 2),
    }


def custody_monthly(face_value: float) -> float:
    """رسم الحفظ الشهري التقديري (0.02% سنويًا ÷ 12)."""
    return round(face_value * C.LEDGER_CUSTODY_ANNUAL_RATE / 12, 2)


def _csv_safe(v: Any) -> Any:
    """نص بيبدأ بـ = + - @ ممكن Excel يعتبره معادلة: بنحط قدامه ' عشان يتعرض كنص."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    """كل أعمدة الدفتر كـ CSV (الرسوم غير المعروفة بتتساب فاضية، مش صفر)."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_LEDGER_COLS)
    for r in rows:
        w.writerow(
            ["" if r.get(c) is None else _csv_safe(r.get(c)) for c in _LEDGER_COLS]
        )
    return buf.getvalue()


def report_to_csv(rep: "AnnualReport") -> str:
    """التقرير السنوي كـ CSV: الأذون اللي نزلت فلوسها في السنة + سطر الإجمالي."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["id", "tenor_days", "face_value", "credit_date", "gross", "tax", "fees", "net"]
    )
    for r in rep.realized_rows:
        w.writerow(
            [
                r["id"],
                r["tenor_days"],
                r["face_value"],
                r["actual_credit_date"],
                round(proceeds(r) - float(r["actual_purchase_debit"]), 2),
                r["actual_tax_debit"],
                r["actual_fees"],
                round(realized_net(r), 2),
            ]
        )
    w.writerow(
        [
            f"total {period_label(rep.year, rep.half)}",
            rep.count,
            "",
            "",
            round(rep.gross, 2),
            round(rep.tax, 2),
            round(rep.fees, 2),
            round(rep.net, 2),
        ]
    )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ملخص الصفحة والخط الزمني
# ---------------------------------------------------------------------------
STATUS_OPEN = "open"
STATUS_NEAR = "near"
STATUS_OVERDUE = "overdue"
STATUS_SETTLED = "settled"
STATUS_SOLD = "sold"

STATUS_LABELS = {
    STATUS_OPEN: "مفتوح",
    STATUS_NEAR: "قرب يستحق",
    STATUS_OVERDUE: "استحق ولسه من غير أرقام كشف",
    STATUS_SETTLED: "نزلت فلوسه (من الكشف)",
    STATUS_SOLD: "اتباع (تقدير)",
}


def bill_status(row: Dict[str, Any], today: date) -> str:
    if is_settled(row):
        return STATUS_SETTLED
    if is_sold(row):
        return STATUS_SOLD
    days_left = (row["maturity_date"] - today).days
    if days_left < 0:
        return STATUS_OVERDUE
    if days_left <= C.LEDGER_NEAR_MATURITY_DAYS:
        return STATUS_NEAR
    return STATUS_OPEN


def is_open(row: Dict[str, Any]) -> bool:
    return not is_settled(row) and not is_sold(row)


def top_summary(rows: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """3 أرقام الصفحة: المستثمر، الصافي المتوقع، أقرب استحقاق (كلها للأذون المفتوحة)."""
    open_rows = [r for r in rows if is_open(r)]
    invested = sum(
        float(
            r["actual_purchase_debit"]
            if r.get("actual_purchase_debit") is not None
            else r["purchase_price"]
        )
        for r in open_rows
    )
    upcoming = [r for r in open_rows if r["maturity_date"] >= today]
    pool = upcoming or open_rows
    nearest = min(pool, key=lambda r: r["maturity_date"]) if pool else None
    return {
        "open_count": len(open_rows),
        "invested": invested,
        "face_open": sum(float(r["face_value"]) for r in open_rows),
        "expected_net": sum(expected_net(r) for r in open_rows),
        "nearest": nearest,
        "nearest_days": (nearest["maturity_date"] - today).days if nearest else None,
    }


def timeline_items(rows: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """لكل أذن: شريط من الإصدار للاستحقاق، نسبة اللي عدّى، والحالة."""
    items = []
    for r in rows:
        total = max((r["maturity_date"] - r["issue_date"]).days, 1)
        passed = (today - r["issue_date"]).days
        pct = max(0.0, min(100.0, passed / total * 100))
        st_ = bill_status(r, today)
        if st_ in (STATUS_SETTLED, STATUS_SOLD):
            pct = 100.0
        items.append(
            {
                "id": r["id"],
                "status": st_,
                "pct": round(pct, 1),
                "days_left": (r["maturity_date"] - today).days,
                "issue_date": r["issue_date"],
                "maturity_date": r["maturity_date"],
                "tenor_days": r["tenor_days"],
                "face_value": float(r["face_value"]),
                "yield_rate": float(r["yield_rate"]),
            }
        )
    items.sort(
        key=lambda i: (i["status"] in (STATUS_SETTLED, STATUS_SOLD), i["maturity_date"])
    )
    return items


def cap_timeline(items: List[Dict[str, Any]]):
    """للدفتر الكبير: المفتوح (لحد حد أقصى) وأحدث المنزّل بس. بيرجع (items, عدد المخفي)."""
    done = (STATUS_SETTLED, STATUS_SOLD)
    closed = [i for i in items if i["status"] in done]
    opened = [i for i in items if i["status"] not in done]
    keep_o = opened[: C.LEDGER_TIMELINE_MAX_OPEN]
    keep_c = sorted(closed, key=lambda i: i["maturity_date"], reverse=True)[
        : C.LEDGER_TIMELINE_MAX_CLOSED
    ]
    return keep_o + keep_c, len(items) - len(keep_o) - len(keep_c)


# ---------------------------------------------------------------------------
# تنبيه الاستحقاق (بيرجّع نصوص بس، الإرسال في scripts/ledger_maturity_alert.py)
# ---------------------------------------------------------------------------
ALERT_WINDOW_DAYS = 4


def due_alerts(
    rows: List[Dict[str, Any]], today: date, window: int = ALERT_WINDOW_DAYS
) -> List[Dict[str, Any]]:
    """
    أذون مفتوحة بتستحق خلال `window` يوم (أو استحقت ومفيش أرقام كشف)، ولسه ماتنبّهش عليها.
    الشغل بيتم مرتين في الأسبوع، فبنستخدم نافذة مش يوم بالظبط. alerted_on بيمنع التكرار.
    """
    out = []
    for r in rows:
        if not is_open(r) or r.get("alerted_on") is not None:
            continue
        days_left = (r["maturity_date"] - today).days
        if days_left > window:
            continue
        out.append(
            {
                "id": r["id"],
                "days_left": days_left,
                "maturity_date": r["maturity_date"],
                "face_value": float(r["face_value"]),
                "expected_tax": float(r["tax_amount"]),
                "expected_net": expected_net(r),
            }
        )
    out.sort(key=lambda a: a["maturity_date"])
    return out


def alert_text(a: Dict[str, Any]) -> str:
    d = a["days_left"]
    if d < 0:
        head = f"أذن #{a['id']} استحق من {-d} يوم ({a['maturity_date'].isoformat()}) وأرقام الكشف لسه مش مسجلة"
    elif d == 0:
        head = f"أذن #{a['id']} بيستحق النهارده ({a['maturity_date'].isoformat()})"
    else:
        head = f"أذن #{a['id']} بيستحق بعد {d} يوم ({a['maturity_date'].isoformat()})"
    return (
        f"⏰ {head}\n"
        f"القيمة الاسمية: {a['face_value']:,.2f} جنيه\n"
        f"الضريبة المتوقعة (تقدير): {a['expected_tax']:,.2f} جنيه\n"
        f"الصافي المتوقع (تقدير): {a['expected_net']:,.2f} جنيه"
    )


# ---------------------------------------------------------------------------
# عدّاد الاستحقاق الحي: الهدف بداية يوم الاستحقاق بتوقيت القاهرة
# ---------------------------------------------------------------------------
def maturity_epoch_ms(maturity: date) -> int:
    """لحظة بداية يوم الاستحقاق بتوقيت القاهرة (مع الـ DST الصح) كـ epoch بالميلي ثانية."""
    from datetime import datetime, time as dtime

    from timeutil import cairo_tz

    target = cairo_tz().localize(datetime.combine(maturity, dtime(0, 0)))
    return int(target.timestamp() * 1000)


def countdown_text(remaining_ms: int) -> str:
    """نفس صيغة الـ JavaScript بالظبط (الاتنين لازم يطلعوا نفس النص)."""
    neg = remaining_ms < 0
    minutes = abs(remaining_ms) // 60000
    d, rem = divmod(minutes, 1440)
    h, m = divmod(rem, 60)
    if neg:
        return f"عدّى بـ {d} يوم {h} س" if d else f"عدّى بـ {h} س {m} د"
    if d:
        return f"فاضل {d} يوم {h} س {m} د"
    return f"فاضل {h} س {m} د" if h else f"فاضل {m} د"


def countdown_html(maturity: date, now_ms: int) -> str:
    t = maturity_epoch_ms(maturity)
    return f"<span class='cd' data-t='{t}'>{countdown_text(t - now_ms)}</span>"
