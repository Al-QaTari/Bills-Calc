# ui/historical_data_view.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils import prepare_arabic_text
from state_manager import StateManager
import constants as C
import market_compare as mc
from tenors import normalize_tenor_column
from datetime import timedelta


def render_historical_data_view():
    """عرض البيانات التاريخية للعوائد"""
    df = StateManager.get("historical_df", pd.DataFrame())
    if df.empty:
        st.error(prepare_arabic_text("⚠️ لا توجد بيانات تاريخية متاحة."))
        st.info(
            prepare_arabic_text(
                "💡 يمكنك تحديث البيانات من الصفحة الرئيسية للحصول على بيانات تاريخية."
            )
        )
        return

    # توحيد الأجل (357/336 -> 364) عشان أذن السنة يظهر كأجل واحد في الجداول والرسوم
    df = normalize_tenor_column(
        df, C.TENOR_COLUMN_NAME, C.SESSION_DATE_COLUMN_NAME
    ).copy()
    if df.empty:
        st.error(prepare_arabic_text("⚠️ لا توجد بيانات تاريخية متاحة."))
        return

    df[C.DATE_COLUMN_NAME] = pd.to_datetime(df[C.DATE_COLUMN_NAME])
    df = df.sort_values(by=C.DATE_COLUMN_NAME)

    all_tenors = sorted(df[C.TENOR_COLUMN_NAME].unique())
    min_date = df[C.DATE_COLUMN_NAME].min().date()
    max_date = df[C.DATE_COLUMN_NAME].max().date()

    color_map = {"364 يوم": "#FFD700"}  # لون مميز لأجل السنة

    with st.expander(prepare_arabic_text("⚙️ خيارات العرض والتصفية"), expanded=True):
        # ================== الجزء الذي تم تعديله ==================
        # عكس ترتيب الأعمدة لتناسب الواجهة العربية
        col1, col2 = st.columns([2, 3])

        # ================== نهاية الجزء المعدل ==================

        with col1:
            st.markdown(
                f"<h6 class='view-header'>{prepare_arabic_text('تصفية البيانات')}</h6>",
                unsafe_allow_html=True,
            )
            selected_tenors = st.multiselect(
                prepare_arabic_text("آجال الأذون (أيام)"),
                options=all_tenors,
                default=all_tenors,
                format_func=lambda x: f"{x} يوم",
            )

            date_filter_type = st.radio(
                "نوع الفترة الزمنية",
                ["فترة محددة", "آخر 30 يوم", "آخر 90 يوم", "آخر سنة", "كل البيانات"],
                horizontal=True,
                index=2,
                key="date_filter_type",
            )

            if date_filter_type == "فترة محددة":
                start_date = st.date_input(
                    "تاريخ البداية",
                    max(min_date, (max_date - timedelta(days=90))),
                    min_value=min_date,
                    max_value=max_date,
                )
                end_date = st.date_input(
                    "تاريخ النهاية", max_date, min_value=min_date, max_value=max_date
                )
            else:
                end_date = max_date

            if date_filter_type == "آخر 30 يوم":
                start_date = max(min_date, (max_date - timedelta(days=30)))
            elif date_filter_type == "آخر 90 يوم":
                start_date = max(min_date, (max_date - timedelta(days=90)))
            elif date_filter_type == "آخر سنة":
                start_date = max(min_date, (max_date - timedelta(days=365)))
            else:
                start_date = min_date

        with col2:
            st.markdown(
                f"<h6 class='view-header'>{prepare_arabic_text('خيارات العرض')}</h6>",
                unsafe_allow_html=True,
            )
            chart_type = st.selectbox(
                "نوع الرسم البياني", ["خط متصل", "مخطط شريطي", "نقاط"]
            )

        st.markdown("<hr class='content-divider-hr'>", unsafe_allow_html=True)

    filtered_df = df[
        (df[C.TENOR_COLUMN_NAME].isin(selected_tenors))
        & (df[C.DATE_COLUMN_NAME].dt.date >= start_date)
        & (df[C.DATE_COLUMN_NAME].dt.date <= end_date)
    ].copy()  # إنشاء نسخة لتجنب SettingWithCopyWarning

    # إضافة معلومات تشخيصية للبيانات المصفاة

    if filtered_df.empty:
        st.warning(prepare_arabic_text("لا توجد بيانات تطابق معايير التصفية المحددة."))
        return

    st.markdown(
        f"<div class='section-title' style='text-align:center'><h3 style='text-align:center'>{prepare_arabic_text('تطور معدلات العائد')}</h3></div>",
        unsafe_allow_html=True,
    )

    # إضافة عمود tenor_label للبيانات المصفاة
    filtered_df["tenor_label"] = filtered_df[C.TENOR_COLUMN_NAME].astype(str) + " يوم"

    if chart_type == "خط متصل":
        fig = px.line(
            filtered_df,
            x=C.DATE_COLUMN_NAME,
            y=C.YIELD_COLUMN_NAME,
            color="tenor_label",
            labels={"tenor_label": "أجل الاستحقاق"},
            markers=True,
            color_discrete_map=color_map,
        )
        fig.update_layout(
            xaxis_title="التاريخ",
            yaxis_title="معدل العائد (%)",
            hovermode="x unified",
        )
        # توحيد سمك ونوع الخط
        fig.update_traces(line=dict(width=3, dash="solid"))
    elif chart_type == "نقاط":
        fig = px.scatter(
            filtered_df,
            x=C.DATE_COLUMN_NAME,
            y=C.YIELD_COLUMN_NAME,
            color="tenor_label",
            labels={"tenor_label": "أجل الاستحقاق"},
            size_max=10,
            color_discrete_map=color_map,
        )
        fig.update_layout(
            xaxis_title="التاريخ",
            yaxis_title="معدل العائد (%)",
            hovermode="x unified",
        )
    elif chart_type == "مخطط شريطي":
        bar_df = (
            filtered_df.groupby(["tenor_label"])[C.YIELD_COLUMN_NAME]
            .mean()
            .reset_index()
        )
        fig = px.bar(
            bar_df,
            x="tenor_label",
            y=C.YIELD_COLUMN_NAME,
            color="tenor_label",
            labels={"tenor_label": "أجل الاستحقاق"},
            text_auto=".2f",
            color_discrete_map=color_map,
        )
        fig.update_layout(
            xaxis_title="أجل الاستحقاق",
            yaxis_title="معدل العائد (%)",
        )
        # توحيد سمك ونوع حدود الأعمدة
        fig.update_traces(marker_line_width=2, marker_line_color="#333")

    # إضافة تنسيق إضافي للرسم البياني
    fig.update_layout(
        font=dict(family="Arial, sans-serif", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=50, t=80, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": True})

    st.markdown("<hr class='content-divider-hr'>", unsafe_allow_html=True)
    render_market_insights(df, filtered_df)


def _takeaway(html: str) -> None:
    """جملة الخلاصة في صندوق واحد في النص."""
    st.markdown(
        "<div style='text-align:center;direction:rtl;background:rgba(59,130,246,.14);"
        "border:1px solid rgba(59,130,246,.35);border-radius:.75rem;padding:.8rem 1rem;"
        f"font-weight:600;line-height:1.7'>{html}</div>",
        unsafe_allow_html=True,
    )


def _plain_layout(fig, title: str):
    fig.update_layout(
        title=dict(text=prepare_arabic_text(title), x=0.5, xanchor="center"),
        font=dict(family="Arial, sans-serif", size=13),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=30, r=30, t=60, b=40),
        showlegend=False,
        dragmode=False,
    )
    return fig


def _my_open_bills():
    """أذونك المفتوحة، بس لو الدفتر مفتوح بكلمة المرور. غير كده بيرجع None."""
    try:
        import ledger
        import ledger_auth

        if not ledger_auth.is_authenticated():
            return None
        return [r for r in ledger.LedgerStore().list_all() if ledger.is_open(r)]
    except Exception:  # noqa: BLE001  (القاعدة مش متاحة: نكمل من غير أذونك)
        return None


def render_market_insights(df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    """منحنى العائد والتحليل الإحصائي بلغة بسيطة، مقفولين لحد ما تفتحهم."""
    with st.expander("📊 افهم السوق ببساطة (منحنى العائد وإحصائيات)", expanded=False):
        sessions = mc.prepare_sessions(df)
        f_sessions = mc.prepare_sessions(filtered_df)
        latest = mc.latest_by_tenor(sessions)

        st.markdown(
            "<div class='section-title' style='text-align:center'><h3 style='text-align:center'>آخر عائد لكل أجل</h3></div>",
            unsafe_allow_html=True,
        )
        _takeaway(mc.curve_takeaway(latest))
        st.caption("كل عمود هو آخر عطاء نزل لأجل معين. كل ما العمود أعلى، العائد أعلى.")
        if not latest.empty:
            fig = go.Figure(
                go.Bar(
                    x=[f"{int(t)} يوم" for t in latest["tenor"]],
                    y=latest["yield"],
                    text=[f"{y:.2f}%" for y in latest["yield"]],
                    textposition="outside",
                    marker_color="#3b82f6",
                    hovertemplate="%{x}: %{y:.2f}%<extra></extra>",
                )
            )
            bills = _my_open_bills()
            if bills:
                pts = []
                for r in bills:
                    pts.append(
                        (
                            f"{int(mc.normalize_tenor(r['tenor_days']))} يوم",
                            float(r["yield_rate"]),
                            f"أذنك #{r['id']}",
                        )
                    )
                fig.add_trace(
                    go.Scatter(
                        x=[p[0] for p in pts],
                        y=[p[1] for p in pts],
                        mode="markers",
                        marker=dict(color="#FFD700", size=12, symbol="diamond"),
                        text=[p[2] for p in pts],
                        hovertemplate="%{text}: %{y:.2f}%<extra></extra>",
                    )
                )
                st.caption(
                    "💎 الماسة الذهبية هي عائد أذونك المفتوحة، تقارنها بالأعمدة."
                )
            elif bills is None:
                st.caption(
                    "لو دخلت على «محفظتي» بكلمة المرور، هتظهر هنا أذونك على الرسم."
                )
            fig.update_yaxes(title_text="العائد (%)", rangemode="tozero")
            st.plotly_chart(
                _plain_layout(fig, "آخر عائد لكل أجل"),
                width="stretch",
                config={"displayModeBar": False},
            )

        st.markdown("<hr class='content-divider-hr'>", unsafe_allow_html=True)
        st.markdown(
            "<div class='section-title' style='text-align:center'><h3 style='text-align:center'>العائد خلال الفترة اللي اخترتها</h3></div>",
            unsafe_allow_html=True,
        )
        stats = mc.period_stats(f_sessions)
        _takeaway(mc.stats_takeaway(stats))
        if not stats.empty:
            table = pd.DataFrame(
                {
                    "الأجل": [f"{t} يوم" for t in stats["tenor"]],
                    "المتوسط %": stats["avg"],
                    "الأقل %": stats["min"],
                    "الأعلى %": stats["max"],
                    "آخر عائد %": stats["last"],
                }
            )
            cfg = {
                c: st.column_config.Column(alignment="center") for c in table.columns
            }
            st.dataframe(table, width="stretch", hide_index=True, column_config=cfg)
            st.caption(
                "المتوسط هو العائد المعتاد في الفترة، والأقل والأعلى هما أضيق وأوسع عائد "
                "نزل فيها، وآخر عائد هو أحدث عطاء."
            )
