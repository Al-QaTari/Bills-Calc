# ui/portfolio.py
"""دفتر المحفظة: تسجيل شراء الأذون من الحاسبة وعرض الأرباح المتوقعة والمحققة."""

import logging
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ledger
import ledger_auth
import market_compare as mc
import constants as C
from state_manager import StateManager
from timeutil import cairo_now
from utils import format_currency, prepare_arabic_text

logger = logging.getLogger(__name__)

LAST_CALC_KEY = "_ledger_last_calc"


def _get_store():
    """بيرجع LedgerStore أو None (ويعرض الخطأ). مفيش بديل محلي."""
    try:
        return ledger.LedgerStore()
    except ledger.LedgerUnavailable as e:
        st.error(
            f"🔒 دفتر المحفظة مقفول: قاعدة PostgreSQL غير متاحة ({e}). مفيش بيانات اتحفظت."
        )
        return None


def remember_calculation(face_value, yield_rate, tenor_days, tax_rate, result) -> None:
    """بتتنده من الحاسبة بعد كل حساب ناجح، عشان زر الشراء يعرف آخر حساب."""
    st.session_state[LAST_CALC_KEY] = {
        "face_value": float(face_value),
        "yield_rate": float(yield_rate),
        "tenor_days": int(tenor_days),
        "tax_rate": float(tax_rate),
        "purchase_price": float(result.purchase_price),
        "gross_return": float(result.gross_return),
        "tax_amount": float(result.tax_amount),
    }
    st.session_state["ledger_save_open"] = False


def render_save_to_ledger() -> None:
    """زر "اشتريت هذا الأذن" تحت نتائج الحاسبة الأساسية."""
    calc = st.session_state.get(LAST_CALC_KEY)
    flash = st.session_state.pop("ledger_flash", None)
    if flash:
        st.success(flash)
    if not calc:
        return

    if st.button(
        prepare_arabic_text("🛒 اشتريت هذا الأذن"),
        key="ledger_buy_button",
        width="stretch",
    ):
        st.session_state["ledger_save_open"] = True

    if not st.session_state.get("ledger_save_open"):
        return

    with st.container(border=True):
        _heading("📒 تسجيل الشراء في المحفظة")
        if not ledger_auth.require_auth("save"):
            return
        store = _get_store()
        if store is None:
            return

        issue_default = cairo_now().date()
        st.caption(
            "كل حاجة بتتحسب لوحدها: الاستحقاق = الإصدار + الأجل، الضريبة بنسبتك، "
            "ورسوم البنك كتقدير: الشراء 2.5 لكل 100 ألف، الاستحقاق 1 في الألف (كل واحد بحد أقصى 1000)، "
            "والحفظ 0.02% سنويًا. الرسوم دي من جدول رسوم أمين الحفظ ولا تشمل الرسوم السيادية "
            "(المقاصة والإيداع والبنك المركزي والرقابة المالية). "
            "تقدر تعدّل أي رقم قبل الحفظ، أو تحفظ على طول."
        )
        with st.expander("✏️ تعديل التواريخ والرسوم (اختياري)"):
            issue = st.date_input(
                "تاريخ الإصدار (يوم تسليم الأذن ودفع الفلوس)",
                value=issue_default,
                key="ledger_issue_date",
            )
            maturity_default = ledger.maturity_from_issue(issue, calc["tenor_days"])
            maturity = st.date_input(
                f"تاريخ الاستحقاق (الإصدار + {calc['tenor_days']} يوم)",
                value=maturity_default,
                key=f"ledger_maturity_{issue}",
            )
            c1, c2 = st.columns(2)
            with c1:
                redemption_fee = st.number_input(
                    "رسم الاستحقاق (تقدير)",
                    min_value=0.0,
                    value=ledger.estimate_redemption_fee(calc["face_value"]),
                    step=50.0,
                    key=f"ledger_redemption_fee_{int(calc['face_value'])}",
                    help="1 في الألف بحد أقصى 1000 جنيه (حسب جدول الرسوم، مش مؤكد من الكشف).",
                )
            with c2:
                custody_fee = st.number_input(
                    "رسم الحفظ (تقدير)",
                    min_value=0.0,
                    value=ledger.estimate_custody_fee(
                        calc["face_value"], calc["tenor_days"]
                    ),
                    step=10.0,
                    key=f"ledger_custody_fee_{int(calc['face_value'])}_{calc['tenor_days']}",
                    help="0.02% سنويًا. لسه مش مؤكد إنه بيتخصم فعلاً.",
                )
            purchase_fee = st.number_input(
                "رسم الشراء (تقدير)",
                min_value=0.0,
                value=ledger.estimate_purchase_fee(calc["face_value"]),
                step=10.0,
                key=f"ledger_purchase_fee_{int(calc['face_value'])}",
                help="2.5 لكل 100 ألف بحد أقصى 1000 جنيه (حسب جدول الرسوم). مش مؤكد إنه بيتطبق على الإصدار الأولي.",
            )
            note = st.text_input("ملاحظة (اختياري)", key="ledger_note")

        if st.button("💾 احفظ في المحفظة", key="ledger_save_confirm", type="primary"):
            if maturity <= issue:
                st.error("الاستحقاق لازم يكون بعد الإصدار.")
                return
            try:
                new_id = store.add(
                    {
                        "created_on": cairo_now().date(),
                        **calc,
                        "issue_date": issue,
                        "maturity_date": maturity,
                        "purchase_fee": purchase_fee,
                        "redemption_fee": redemption_fee,
                        "custody_fee": custody_fee,
                        "fees_confirmed": False,
                        "confirmed_fields": "",
                        "note": note or None,
                    }
                )
            except Exception as e:  # noqa: BLE001
                logger.error("ledger save failed: %s", type(e).__name__)
                st.error("تعذر الحفظ. مفيش حاجة اتسجلت.")
                return
            st.session_state["ledger_save_open"] = False
            st.session_state["ledger_flash"] = (
                f"✅ اتسجل الأذن في المحفظة (رقم {new_id})."
            )
            st.rerun()


def _money(v):
    return "غير معروف" if v is None else format_currency(v)


def _rows_dataframe(rows) -> pd.DataFrame:
    out = []
    for r in rows:
        rn = ledger.realized_net(r)
        out.append(
            {
                "#": r["id"],
                "الحالة": (
                    "نزلت الفلوس"
                    if ledger.is_settled(r)
                    else "مباع (تقدير)" if ledger.is_sold(r) else "مفتوح"
                ),
                "القيمة الاسمية": r["face_value"],
                "الأجل (يوم)": r["tenor_days"],
                "العائد %": r["yield_rate"],
                "الإصدار (رسمي)": r["issue_date"],
                "الاستحقاق (رسمي)": r["maturity_date"],
                "الضريبة %": r["tax_rate"],
                "الضريبة (تقدير)": round(r["tax_amount"], 2),
                "الرسوم المعروفة": round(ledger.known_fees_total(r), 2),
                "رسوم مؤكدة؟": "نعم" if ledger.fees_complete(r) else "لا (تقدير)",
                "صافي متوقع (تقدير)": round(ledger.expected_net(r), 2),
                "نزول الفلوس (كشف)": r["actual_credit_date"],
                "صافي محقق (كشف)": None if rn is None else round(rn, 2),
            }
        )
    df = pd.DataFrame(out)
    # الأهم أولًا (على اليمين في العربي)، عشان الموبايل يعرض المهم من غير سحب
    first = ["#", "الحالة", "القيمة الاسمية", "الاستحقاق (رسمي)", "صافي متوقع (تقدير)"]
    return df[first + [c for c in df.columns if c not in first]]


def render_sale_to_ledger(inputs, result) -> None:
    """زر "بعت هذا الأذن" تحت نتائج حاسبة البيع الثانوي: بيسجل البيع على أذن مفتوح في المحفظة."""
    flash = st.session_state.pop("ledger_flash_sale", None)
    if flash:
        st.success(flash)
    if not inputs or result is None:
        return
    if st.button(
        "🛒 بعت هذا الأذن (سجّله في المحفظة)", key="ledger_sell_button", width="stretch"
    ):
        st.session_state["ledger_sale_open"] = True
    if not st.session_state.get("ledger_sale_open"):
        return
    with st.container(border=True):
        _heading("📒 تسجيل بيع في السوق الثانوي")
        if not ledger_auth.require_auth("sale"):
            return
        store = _get_store()
        if store is None:
            return
        try:
            open_rows = [
                r
                for r in store.list_all()
                if not ledger.is_settled(r) and not ledger.is_sold(r)
            ]
        except Exception as e:  # noqa: BLE001
            logger.error("ledger read failed: %s", type(e).__name__)
            st.error("تعذر قراءة الدفتر.")
            return
        if not open_rows:
            st.info(
                "مفيش أذون مفتوحة في المحفظة. سجّل الشراء الأول من الحاسبة الأساسية."
            )
            return
        by_id = {r["id"]: r for r in open_rows}
        sel = st.selectbox(
            "أي أذن بعته؟",
            options=list(by_id),
            format_func=lambda i: (
                f"#{i} • {by_id[i]['face_value']:,.0f} • {by_id[i]['tenor_days']} يوم"
            ),
            key="ledger_sale_select",
        )
        st.caption(
            f"الإصدار {by_id[sel]['issue_date'].isoformat()} • "
            f"الاستحقاق {by_id[sel]['maturity_date'].isoformat()}"
        )
        sold_on = st.date_input(
            "تاريخ البيع", value=cairo_now().date(), key="ledger_sold_on"
        )
        st.caption(
            f"هيتسجل سعر البيع {format_currency(result.sale_price)} وصافي بعد الضريبة "
            f"{format_currency(result.net_profit)} كتقدير، لحد ما تأكّده من الكشف."
        )
        if st.button("💾 سجّل البيع", key="ledger_sale_confirm", type="primary"):
            try:
                store.update_row(
                    sel,
                    {
                        "sold_on": sold_on,
                        "sale_price": float(result.sale_price),
                        "sale_tax": float(result.tax_amount),
                        "sale_net": float(result.net_profit),
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.error("ledger sale failed: %s", type(e).__name__)
                st.error("تعذر الحفظ. مفيش حاجة اتسجلت.")
                return
            st.session_state["ledger_sale_open"] = False
            st.session_state["ledger_flash_sale"] = f"✅ اتسجل بيع الأذن #{sel}."
            st.rerun()


_TIMELINE_CSS = """
<style>
.tl-wrap{display:flex;flex-direction:column;gap:.55rem;margin:.4rem 0 1rem}
.tl-row{display:grid;grid-template-columns:7.5rem 1fr 11rem;gap:.75rem;align-items:center;
 background:var(--surface-color);border:1px solid var(--surface-border);border-radius:12px;padding:.55rem .8rem}
.tl-name{font-weight:600;color:var(--text-primary);font-size:.9rem}
.tl-name small{display:block;color:var(--text-muted);font-weight:400}
.tl-track{position:relative;height:.9rem;border-radius:999px;background:var(--surface-color-alt);
 border:1px solid var(--surface-border);overflow:hidden}
.tl-fill{height:100%;border-radius:999px}
.tl-dates{display:flex;justify-content:space-between;color:var(--text-muted);font-size:.72rem;margin-top:.2rem}
.tl-cmp{text-align:center;font-size:.74rem;margin-top:.2rem;color:var(--text-muted)}
.tl-cmp-better{color:var(--color-success-text)} .tl-cmp-weaker{color:var(--color-warning-text)}
.tl-status{text-align:center;white-space:nowrap;font-size:.8rem;font-weight:600;border-radius:999px;padding:.2rem .5rem;border:1px solid}
.tl-open .tl-fill{background:var(--color-primary)} .tl-open .tl-status{color:var(--color-primary-light);border-color:var(--color-primary)}
.tl-near .tl-fill{background:var(--color-warning)} .tl-near .tl-status{color:var(--color-warning-text);border-color:var(--color-warning)}
.tl-overdue .tl-fill{background:var(--color-danger)} .tl-overdue .tl-status{color:var(--color-danger-text);border-color:var(--color-danger)}
.tl-settled .tl-fill{background:var(--color-success)} .tl-settled .tl-status{color:var(--color-success-text);border-color:var(--color-success)}
.tl-sold .tl-fill{background:var(--color-secondary)} .tl-sold .tl-status{color:var(--color-secondary-light);border-color:var(--color-secondary)}
.tl-legend{display:flex;flex-wrap:wrap;gap:.9rem;color:var(--text-muted);font-size:.8rem;margin-bottom:.3rem}
.tl-dot{display:inline-block;width:.65rem;height:.65rem;border-radius:50%;margin-inline-end:.3rem}
.metric-sub{display:block;margin-top:.35rem;font-size:.85rem;color:var(--text-muted);font-weight:400}
@media (max-width:640px){.tl-row{grid-template-columns:1fr}}
</style>
"""


def _now_ms() -> int:
    """الوقت الحالي (epoch ms) في كل render، من غير كاش."""
    return int(time.time() * 1000)


_COUNTDOWN_JS = """
<script>
(function () {
  var P = window.parent, d;
  try { d = P.document; } catch (e) { return; }
  if (P.__tbCountdown) { P.clearInterval(P.__tbCountdown); }
  function fmt(ms) {
    var neg = ms < 0, mins = Math.floor(Math.abs(ms) / 60000);
    var dd = Math.floor(mins / 1440), hh = Math.floor((mins % 1440) / 60), mm = mins % 60;
    if (neg) { return dd ? "عدّى بـ " + dd + " يوم " + hh + " س" : "عدّى بـ " + hh + " س " + mm + " د"; }
    if (dd) { return "فاضل " + dd + " يوم " + hh + " س " + mm + " د"; }
    return hh ? "فاضل " + hh + " س " + mm + " د" : "فاضل " + mm + " د";
  }
  function tick() {
    if (d.hidden) { return; }
    var els = d.querySelectorAll(".cd[data-t]"), now = Date.now();
    for (var i = 0; i < els.length; i++) {
      var t = fmt(+els[i].getAttribute("data-t") - now);
      if (els[i].textContent !== t) { els[i].textContent = t; }
    }
  }
  tick();
  P.__tbCountdown = P.setInterval(tick, 15000);
})();
</script>
"""


def render_top_cards(rows) -> None:
    """3 كروت كبيرة: المستثمر، الصافي المتوقع، أقرب استحقاق."""
    t = ledger.top_summary(rows, cairo_now().date())
    nearest = t["nearest"]
    if nearest is None:
        nearest_value, nearest_sub = "—", "مفيش أذون مفتوحة"
    else:
        nearest_value = ledger.countdown_html(nearest["maturity_date"], _now_ms())
        nearest_sub = f"{nearest['maturity_date'].isoformat()} • {format_currency(nearest['face_value'])}"
    c1, c2, c3 = st.columns(3)
    cards = [
        (
            c1,
            "blue",
            (
                "إجمالي المستثمر (أذون مفتوحة)"
                if t["invested_confirmed_count"] == t["open_count"]
                else "إجمالي المستثمر (تقدير)"
            ),
            format_currency(t["invested"]),
            f"{t['open_count']} أذن • قيمة اسمية {format_currency(t['face_open'])}"
            f" • مؤكد من الكشف {t['invested_confirmed_count']} من {t['open_count']}",
        ),
        (
            c2,
            "green-dark",
            "الربح الصافي المتوقع (تقدير)",
            format_currency(t["expected_net"]),
            "بعد الضريبة والرسوم التقديرية",
        ),
        (c3, "yellow", "أقرب استحقاق", nearest_value, nearest_sub),
    ]
    for col, color, title, value, sub in cards:
        _card(col, color, title, value, sub)


def render_timeline(rows) -> None:
    """خط زمني: شريط لكل أذن من الإصدار للاستحقاق، ملوّن بحالته."""
    items, hidden = ledger.cap_timeline(ledger.timeline_items(rows, cairo_now().date()))
    colors = {
        ledger.STATUS_OPEN: "var(--color-primary)",
        ledger.STATUS_NEAR: "var(--color-warning)",
        ledger.STATUS_OVERDUE: "var(--color-danger)",
        ledger.STATUS_SETTLED: "var(--color-success)",
        ledger.STATUS_SOLD: "var(--color-secondary)",
    }
    legend = "".join(
        f"<span><span class='tl-dot' style='background:{colors[k]}'></span>{v}</span>"
        for k, v in ledger.STATUS_LABELS.items()
    )
    html = [
        _TIMELINE_CSS,
        f"<div class='tl-legend'>{legend}</div><div class='tl-wrap'>",
    ]
    sessions = mc.prepare_sessions(StateManager.get("historical_df", pd.DataFrame()))
    for i in items:
        cmp_ = mc.compare_bill(
            sessions, i["tenor_days"], i["yield_rate"], i["issue_date"]
        )
        cmp_cls = cmp_["status"]
        cmp_line = f"<div class='tl-cmp tl-cmp-{cmp_cls}'>{mc.bill_line(cmp_)}</div>"
        if i["status"] == ledger.STATUS_SETTLED:
            label = "نزلت الفلوس"
        elif i["status"] == ledger.STATUS_SOLD:
            label = "اتباع"
        else:
            label = ledger.countdown_html(i["maturity_date"], _now_ms())
        html.append(
            f"<div class='tl-row tl-{i['status']}'>"
            f"<div class='tl-name'>#{i['id']} • {i['tenor_days']} يوم"
            f"<small>{format_currency(i['face_value'])}</small></div>"
            f"<div><div class='tl-track'><div class='tl-fill' style='width:{i['pct']}%'></div></div>"
            f"<div class='tl-dates'><span>{i['issue_date'].isoformat()}</span>"
            f"<span>{i['maturity_date'].isoformat()}</span></div>{cmp_line}</div>"
            f"<div class='tl-status'>{label}</div></div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)
    if hidden:
        st.caption(f"مخفي {hidden} أذن قديم من الخط الزمني. كلهم في الجدول والـ CSV.")


_CENTER_CSS = """
<style>
.pf-h{text-align:center;font-size:1.25rem;font-weight:700;color:var(--text-primary);margin:1.4rem 0 .6rem}
[data-testid="stCaptionContainer"],[data-testid="stAlert"],[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p{text-align:center;justify-content:center;width:100%}
[data-testid="stElementContainer"]:has([data-testid="stRadio"]){width:100% !important}
[data-testid="stRadio"],[data-testid="stRadio"] > div{width:100%;align-items:center}
[data-testid="stRadio"] [role="radiogroup"]{justify-content:center;width:100%}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div{justify-content:center}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div > div:first-child{flex:1 1 auto;justify-content:center;text-align:center;display:flex}
[data-testid="stSelectbox"] [data-baseweb="select"] div[value],[data-testid="stSelectbox"] [data-baseweb="select"] input{text-align:center}
[data-testid="stFormSubmitButton"]{display:flex;justify-content:center}
.stButton,.stDownloadButton{display:flex;justify-content:center}
[data-testid="stForm"],[data-testid="stCheckbox"]{text-align:center}
[data-testid="stCheckbox"]{display:flex;justify-content:center}
.metric-card .metric-sub{text-align:center}
/* ستريمليت 1.65: الخانة المقفولة input والقائمة بصفوف ارتفاعها ثابت، فلف النص مش ممكن.
   عشان كده اسم الأذن قصير (رقم • قيمة • أجل) والتواريخ في السطر اللي تحته. أي نص أطول بيتقطع بـ ... */
[data-testid="stSelectbox"] input{text-overflow:ellipsis;text-align:center}
[role="listbox"] [role="option"]{overflow:hidden;text-overflow:ellipsis;justify-content:center;text-align:center}
</style>
"""


def _heading(text: str) -> None:
    st.markdown(f"<div class='pf-h'>{text}</div>", unsafe_allow_html=True)


def _card(col, color: str, title: str, value: str, sub: str) -> None:
    sub_html = f"<span class='metric-sub'>{sub}</span>" if sub else ""
    col.markdown(
        f"<div class='metric-card {color}'><span class='metric-title'>{title}</span>"
        f"<span class='metric-value'>{value}</span>{sub_html}</div>",
        unsafe_allow_html=True,
    )


def _show_table(df: pd.DataFrame) -> None:
    if len(df) > C.LEDGER_TABLE_MAX_ROWS:
        st.caption(
            f"الجدول بيعرض أحدث {C.LEDGER_TABLE_MAX_ROWS} من {len(df)}. الدفتر كله في الـ CSV."
        )
        df = df.head(C.LEDGER_TABLE_MAX_ROWS)
    st.caption("اسحب الجدول يمين وشمال لو فيه أعمدة زيادة.")
    cfg = {
        c: st.column_config.Column(
            alignment="center", width="small" if c == "الحالة" else None
        )
        for c in df.columns
    }
    st.dataframe(df, width="stretch", hide_index=True, column_config=cfg)


def _render_statement_confirmation(store, sel, r) -> None:
    """
    كل قيمة من كشف الحساب ليها زر "تأكيد القيمة" تحتها. القيمة المعروضة تقدير لحد ما
    تتأكد. الربح المحقق مابيتحسبش إلا لما كل القيم المطلوبة تتأكد.
    """
    st.caption(
        "الأرقام هنا متعبية مقدمًا بالتقدير. قارنها بكشف حسابك، عدّلها لو مختلفة، "
        "وبعدين اضغط «تأكيد القيمة» تحت كل رقم. الرقم مابيتحسبش من الكشف إلا بعد التأكيد."
    )
    est_fees = ledger.known_fees_total(r)
    sale_proceeds = r["sale_price"] if ledger.is_sold(r) else None
    # (مفتاح، نوع الحقل، القيمة المبدئية التقديرية، خطوة)
    fields = [
        ("purchase_debit_date", "date", r["issue_date"], None),
        ("purchase_debit", "money", float(r["purchase_price"]), 100.0),
        ("credit_date", "date", r["maturity_date"], None),
        (
            "proceeds",
            "money",
            float(sale_proceeds if sale_proceeds is not None else r["face_value"]),
            100.0,
        ),
        ("tax", "money", float(r["tax_amount"]), 10.0),
        ("fees", "money", float(est_fees), 10.0),
    ]
    done = ledger.confirmed_fields(r)
    for key, kind, estimate, step in fields:
        col, label = ledger.CONFIRM_FIELDS[key]
        saved = r.get(col)
        initial = saved if (key in done and saved is not None) else estimate
        wkey = f"ledger_f_{sel}_{key}"
        with st.container(border=True):
            if kind == "date":
                value = st.date_input(label, value=initial, key=wkey)
            else:
                value = st.number_input(
                    label,
                    min_value=0.0,
                    value=float(initial),
                    step=step,
                    key=wkey,
                )
            status = ledger.field_status(r, key, value)
            if status == "confirmed":
                st.success("✅ مؤكد من كشف الحساب")
            elif status == "changed":
                shown = saved.isoformat() if kind == "date" else f"{saved:,.2f}"
                st.warning(
                    f"غيّرت الرقم بعد التأكيد. المؤكد المحفوظ لسه {shown}. "
                    "اضغط «تأكيد القيمة» عشان القيمة الجديدة تتحفظ."
                )
            else:
                st.info("تقدير (لسه مش مؤكد من الكشف)")
            if status != "confirmed" and st.button(
                "تأكيد القيمة",
                key=f"ledger_c_{sel}_{key}",
                width="stretch",
            ):
                try:
                    store.update_row(
                        sel,
                        ledger.confirm_field_update(
                            r, key, value if kind == "date" else float(value)
                        ),
                    )
                except Exception as e:  # noqa: BLE001
                    logger.error("ledger confirm failed: %s", type(e).__name__)
                    st.error("تعذر الحفظ (القاعدة مش متاحة). مفيش حاجة اتغيرت.")
                    return
                st.rerun()
    missing = [
        ledger.CONFIRM_FIELDS[k][1] for k in ledger.REQUIRED_FOR_PROFIT if k not in done
    ]
    if missing:
        st.warning(
            "الربح المحقق مش هيتحسب لحد ما تتأكد كل القيم. لسه: " + "، ".join(missing)
        )
    else:
        st.success("كل القيم متأكدة، والربح المحقق لهذا الأذن بيتحسب من الكشف.")


def render_portfolio() -> None:
    """قسم "محفظتي": محمي بكلمة مرور."""
    st.markdown(_CENTER_CSS, unsafe_allow_html=True)
    if not ledger_auth.require_auth("portfolio"):
        return
    store = _get_store()
    if store is None:
        return

    flash_del = st.session_state.pop("ledger_flash_del", None)
    if flash_del:
        st.success(flash_del)

    _, mid, _ = st.columns([2, 1, 2])
    with mid:
        if st.button("🚪 خروج", key="ledger_logout", width="stretch"):
            ledger_auth.logout()
            st.rerun()

    try:
        rows = store.list_all()
    except Exception as e:  # noqa: BLE001
        logger.error("ledger read failed: %s", type(e).__name__)
        st.error("تعذر قراءة الدفتر.")
        return

    if not rows:
        st.info("الدفتر فاضي. احسب أذن من الحاسبة الأساسية واضغط «اشتريت هذا الأذن».")
        return

    s = ledger.summarize(rows, cairo_now().date())
    render_top_cards(rows)
    _heading("الخط الزمني للأذون")
    render_timeline(rows)
    components.html(_COUNTDOWN_JS, height=0)

    years = sorted({ledger.period_date(r).year for r in rows}, reverse=True)
    _heading("التقرير السنوي / النصف سنوي")
    if len(years) <= 8:  # أزرار أفقية في النص (أنضف وأسهل على الموبايل)
        year = st.radio("السنة", years, horizontal=True, key="ledger_report_year")
    else:
        year = st.selectbox("السنة", years, key="ledger_report_year")
    period = st.radio(
        "الفترة",
        ["السنة كلها", "النصف الأول (يناير-يونيو)", "النصف الثاني (يوليو-ديسمبر)"],
        horizontal=True,
        key="ledger_report_period",
    )
    half = None if period == "السنة كلها" else (1 if "الأول" in period else 2)
    rep = ledger.annual_report(rows, year, half)
    plabel = (
        str(year)
        if half is None
        else f"{year} ({'النصف الأول' if half == 1 else 'النصف الثاني'})"
    )
    _heading(f"الأذون اللي استحقاقها في {plabel} ({len(rep.entered)})")
    if rep.entered:
        _show_table(_rows_dataframe(rep.entered))
    else:
        st.caption("مفيش أذون اتسجلت في السنة دي.")
    with st.container(border=True):
        _heading(f"الربح المحقق في {plabel} (من كشف الحساب فقط، {rep.count} أذن)")
        r1, r2, r3, r4 = st.columns(4)
        for col, color, title, val in (
            (r1, "blue", "العائد الإجمالي", rep.gross),
            (r2, "yellow", "الضرايب المدفوعة", rep.tax),
            (r3, "purple", "رسوم البنك", rep.fees),
            (r4, "green-dark", "الصافي النهائي", rep.net),
        ):
            _card(col, color, title, format_currency(val), "")
        st.caption(
            "الأذن بيتحسب في الفترة اللي فيها تاريخ استحقاقه (والمباع قبل الاستحقاق بتاريخ البيع)، حتى لو اتسجل في سنة قبلها."
        )
    if rep.realized_missing_numbers:
        st.warning(
            f"{rep.realized_missing_numbers} أذن استحقاقها في {plabel} وأرقام الكشف ناقصة، "
            "فمش داخلة في الصافي."
        )
    if rep.open_from_year:
        st.info(
            f"{len(rep.open_from_year)} أذن استحقاقها في {plabel} لسه مفتوحة. "
            f"صافيها المتوقع (تقدير، مش محسوب فوق): {format_currency(rep.open_expected_net)}"
        )
    if s.unsettled_past_maturity:
        st.warning(
            f"{s.unsettled_past_maturity} أذن عدّى استحقاقها ولسه ماسجلتش أرقام الكشف. "
            "سجّلها تحت عشان تتحسب في الربح المحقق."
        )
    if s.unconfirmed_fee_rows:
        st.caption(
            "الرسوم في الصفوف غير المؤكدة تقدير، ورسم الشراء غير المعروف مش محسوب."
        )

    _show_table(_rows_dataframe(rows))

    _heading("تصدير نسخة (CSV)")
    e1, e2 = st.columns(2)
    stamp = cairo_now().strftime("%Y%m%d")
    e1.download_button(
        "⬇️ تحميل الدفتر كله (CSV)",
        data=("\ufeff" + ledger.rows_to_csv(rows)).encode("utf-8"),
        file_name=f"tbill_ledger_{stamp}.csv",
        mime="text/csv",
        key="ledger_csv_all",
        width="stretch",
    )
    e2.download_button(
        f"⬇️ تحميل تقرير {plabel} (CSV)",
        data=("\ufeff" + ledger.report_to_csv(rep)).encode("utf-8"),
        file_name=f"tbill_report_{ledger.period_label(year, half).replace(' ', '_')}.csv",
        mime="text/csv",
        key="ledger_csv_report",
        width="stretch",
    )

    _heading("تأكيد من كشف الحساب / تعديل / حذف")
    by_id = {r["id"]: r for r in rows}
    sel = st.selectbox(
        "اختار الأذن",
        options=list(by_id.keys()),
        format_func=lambda i: (
            f"#{i} • {by_id[i]['face_value']:,.0f} • {by_id[i]['tenor_days']} يوم"
        ),
        key="ledger_select",
    )
    r = by_id[sel]
    st.caption(
        f"الإصدار {r['issue_date'].isoformat()} • الاستحقاق {r['maturity_date'].isoformat()}"
    )

    with st.expander("🧾 الحركات المتوقعة على الحساب (تقدير تلقائي)"):
        tl = pd.DataFrame(ledger.expected_timeline(r)).rename(
            columns={"date": "التاريخ", "item": "البند", "amount": "المبلغ"}
        )
        st.dataframe(tl, width="stretch", hide_index=True)
        st.caption("التواريخ والمبالغ دي تقدير. اللي في كشف حسابك هو المرجع.")

    _render_statement_confirmation(store, sel, r)

    with st.expander("🗑️ حذف هذا الأذن"):
        sure = st.checkbox("متأكد إني عايز أحذفه", key=f"ledger_del_ok_{sel}")
        if st.button("احذف", key=f"ledger_del_{sel}", disabled=not sure):
            try:
                store.delete_row(sel)
            except Exception as e:  # noqa: BLE001
                logger.error("ledger delete failed: %s", type(e).__name__)
                st.error("تعذر الحذف (القاعدة مش متاحة). مفيش حاجة اتمسحت.")
                return
            st.session_state["ledger_flash_del"] = f"🗑️ اتحذف الأذن #{sel}."
            st.rerun()
