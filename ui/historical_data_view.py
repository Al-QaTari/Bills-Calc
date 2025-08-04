# ui/historical_data_view.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils import prepare_arabic_text
from state_manager import StateManager
import constants as C
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
            show_yield_curve = st.checkbox("عرض منحنى العائد", value=True)

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
        f"<div class='section-title'><h3>{prepare_arabic_text('تطور معدلات العائد')}</h3></div>",
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

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})

    # عرض منحنى العائد إذا تم تحديد الخيار
    if show_yield_curve and not filtered_df.empty:
        st.markdown("<hr class='content-divider-hr'>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='section-title'><h3>{prepare_arabic_text('منحنى العائد')}</h3></div>",
            unsafe_allow_html=True,
        )

        # اختيار آخر تاريخ متاح
        selected_date = filtered_df[C.DATE_COLUMN_NAME].max()
        yield_curve_data = filtered_df[filtered_df[C.DATE_COLUMN_NAME] == selected_date]

        if not yield_curve_data.empty:
            yield_curve_fig = go.Figure()
            yield_curve_fig.add_trace(
                go.Scatter(
                    x=yield_curve_data[C.TENOR_COLUMN_NAME],
                    y=yield_curve_data[C.YIELD_COLUMN_NAME],
                    mode="lines+markers",
                    line=dict(color="#1f77b4", width=3),
                    marker=dict(size=8),
                    hovertemplate="%{x} يوم: %{y:.2f}%<extra></extra>",
                )
            )

            # إضافة تنسيق إضافي للرسم البياني
            yield_curve_fig.update_layout(
                xaxis_title="أجل الاستحقاق (أيام)",
                yaxis_title="معدل العائد (%)",
                font=dict(family="Arial, sans-serif", size=12),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=50, r=50, t=80, b=50),
                hovermode="x unified",
            )

            st.plotly_chart(
                yield_curve_fig,
                use_container_width=True,
                config={"displayModeBar": True},
            )
            st.caption(
                "ℹ️ **كيف تقرأ الرسم البياني:** هذا هو 'منحنى العائد'، وهو يوضح العلاقة بين العائد و'أجل الاستحقاق'."
            )

    st.markdown("<hr class='content-divider-hr'>", unsafe_allow_html=True)

    # تحليل إحصائي
    st.markdown(
        f"<h6 class='view-header'>{prepare_arabic_text('التحليل الإحصائي')}</h6>",
        unsafe_allow_html=True,
    )

    stats_df = (
        filtered_df.groupby(C.TENOR_COLUMN_NAME)[C.YIELD_COLUMN_NAME]
        .agg(["mean", "min", "max", "std"])
        .round(3)
    )
    stats_df = stats_df.rename(
        columns={
            "mean": "المتوسط",
            "min": "الحد الأدنى",
            "max": "الحد الأعلى",
            "std": "الانحراف المعياري",
        }
    )

    volatility_df = stats_df.reset_index()
    volatility_df["tenor_label"] = (
        volatility_df[C.TENOR_COLUMN_NAME].astype(str) + " يوم"
    )

    volatility_fig = px.bar(
        volatility_df,
        x="tenor_label",
        y="الانحراف المعياري",
        color="tenor_label",
        text_auto=".3f",
        labels={"tenor_label": "أجل الاستحقاق"},
        color_discrete_map=color_map,
    )
    # توحيد سمك ونوع حدود الأعمدة
    volatility_fig.update_traces(marker_line_width=2, marker_line_color="#333")

    volatility_fig.update_layout(
        xaxis_title="أجل الاستحقاق",
        yaxis_title="الانحراف المعياري",
        font=dict(family="Arial, sans-serif", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=50, t=80, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    st.plotly_chart(
        volatility_fig, use_container_width=True, config={"displayModeBar": True}
    )

    st.markdown("<div class='spacer-div'></div>", unsafe_allow_html=True)

    st.markdown(
        f"<h6 class='view-header'>{prepare_arabic_text('ملخص إحصائي للعوائد')}</h6>",
        unsafe_allow_html=True,
    )

    formatted_stats_df = stats_df.round(3)
    st.dataframe(formatted_stats_df, use_container_width=True)

    # --- حذف كود عرض جدول جميع الأيام (بما في ذلك المفقودة) ---
    # (تم حذف كود إنشاء merged_df وعرض st.dataframe الخاص به)

    # --- إزالة منطق التحقق من الفجوات في البيانات وعدم عرض أي تحذير أو تفاصيل ---
    # (تم حذف الكود الخاص بالكشف عن الفجوات والعرض المتعلق به)
