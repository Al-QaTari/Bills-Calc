# ui/help_page.py
import streamlit as st
from utils import prepare_arabic_text, format_currency
import constants as C


def render_help_page():
    """Renders the professional and modern help page with expanded content."""

    st.markdown('<div class="help-page-content">', unsafe_allow_html=True)

    with st.expander("🔍 ما هي أذون الخزانة؟", expanded=False):
        st.markdown(
            """
            <span class='text-primary'>أذون الخزانة</span> هي أداة استثمارية حكومية قصيرة الأجل تصدرها وزارة المالية وتطرحها البنوك نيابة عن الحكومة لجمع سيولة من السوق المحلي.
            <br><br>
            **مميزات أذون الخزانة:**
            <ul>
                <li>🔒 <span class='text-success'>أمان مرتفع</span>: مضمونة من الحكومة المصرية.</li>
                <li>💸 <span class='text-warning'>عائد تنافسي</span>: غالباً أعلى من الودائع البنكية.</li>
                <li>🔄 <span class='text-info'>سيولة عالية</span>: يمكن بيعها في أي وقت قبل الاستحقاق.</li>
                <li>🏦 <span class='text-purple'>متاحة عبر البنوك</span>: يمكنك شراؤها من معظم البنوك المحلية.</li>
                <li>⏳ <span class='text-cyan'>آجال متنوعة</span>: 3 أشهر، 6 أشهر، 9 أشهر، 12 شهر.</li>
            </ul>
            <br>
            **كيف تعمل؟**<br>
            تشتري أذون الخزانة بسعر أقل من قيمتها الاسمية (مثلاً تدفع 95,000 جنيه لتحصل على 100,000 جنيه عند الاستحقاق)، والفرق هو العائد.
            <br><br>
            **مثال عملي:**<br>
            إذا اشتريت أذون خزانة بقيمة اسمية 100,000 جنيه لمدة 6 أشهر بسعر شراء 95,000 جنيه، ستحصل على 100,000 جنيه عند الاستحقاق، أي أن العائد هو 5,000 جنيه خلال 6 أشهر.
            """,
            unsafe_allow_html=True,
        )

    with st.expander("❓ الأسئلة الشائعة (FAQ)", expanded=False):
        st.markdown(
            """
            <ul>
                <li><b>ما هو الحد الأدنى لشراء أذون الخزانة؟</b><br>الحد الأدنى عادة 25,000 جنيه، ويختلف حسب البنك.</li>
                <li><b>هل يمكن بيع الأذون قبل الاستحقاق؟</b><br>نعم، يمكن بيعها في السوق الثانوي عبر البنك.</li>
                <li><b>هل العائد ثابت أم متغير؟</b><br>العائد ثابت منذ الشراء حتى الاستحقاق.</li>
                <li><b>هل هناك ضرائب على الأذون؟</b><br>نعم توجد ضرائب.</li>
                <li><b>كيف أتابع نتائج المزادات الجديدة؟</b><br>من خلال موقع البنك المركزي أو التطبيق مباشرة.</li>
                <li><b>هل يمكن الشراء للأبناء أو القصر؟</b><br>نعم، عبر حسابات باسمهم في البنك.</li>
                <li><b>ما الفرق بين أذون وسندات الخزانة؟</b><br>الأذون قصيرة الأجل (حتى سنة)، السندات أطول من سنة.</li>
            </ul>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("💡 نصائح للاستثمار الآمن في أذون الخزانة", expanded=False):
        st.markdown(
            """
            <ul>
                <li>قارن بين عوائد الأذون المختلفة واختر الأنسب لأهدافك.</li>
                <li>تأكد من مراجعة الشروط مع البنك قبل الشراء.</li>
                <li>احتفظ بسجل لمواعيد الاستحقاق لتجنب فقدان العائد.</li>
                <li>استثمر جزءاً من مدخراتك فقط، ووزع استثماراتك.</li>
                <li>تابع نتائج المزادات بانتظام للحصول على أفضل العوائد.</li>
            </ul>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("🧮 تقدير رسوم أمين الحفظ"):
        st.markdown(
            """
            <div class="card fee-card">
                <div class="fee-card-header">
                    <span class="fee-card-icon">🏦</span>
                    <span class="fee-card-title">رسوم أمين الحفظ البنكي</span>
                </div>
                <div class="fee-card-description">
                    تحتفظ البنوك بأذون الخزانة الخاصة بك مقابل رسوم خدمة دورية يمكنك حسابها هنا 
                </div>
            """,
            unsafe_allow_html=True,
        )
        fee_col1, fee_col2 = st.columns(2)
        with fee_col1:
            total_face_value = st.number_input(
                prepare_arabic_text("إجمالي القيمة الإسمية لكل أذونك"),
                min_value=C.MIN_T_BILL_AMOUNT,
                value=25000.0,
                step=C.T_BILL_AMOUNT_STEP,
                key="fee_calc_total",
            )
        with fee_col2:
            fee_percentage = st.number_input(
                prepare_arabic_text("نسبة رسوم الحفظ السنوية (%)"),
                min_value=0.0,
                value=0.10,
                step=0.1,
                format="%.1f",
                key="fee_calc_perc",
            )
        annual_fee = total_face_value * (fee_percentage / 100.0)
        quarterly_deduction = annual_fee / 4
        st.markdown(
            f"""
                <div class='fee-results-container'>
                    <div class='fee-results-label'>الخصم الربع سنوي التقريبي</div>
                    <div class='insight-card fee-results-value'>
                        {format_currency(quarterly_deduction)} 
                    </div>
                    <div class='fee-results-note'>* تُخصم الرسوم تلقائيًا من رصيدك البنكي كل ثلاثة أشهر.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("🔗 مصادر وروابط رسمية"):
        st.markdown(
            """
            <ul>
                <li><a href="https://mof.gov.eg/ar/archive/treasuryBills/general/%D8%A3%D8%B0%D9%88%D9%86%20%D8%A7%D9%84%D8%AE%D8%B2%D8%A7%D9%86%D8%A9" target="_blank">أسعار الأوراق المالية الحكومية</a></li>
                <li><a href="https://www.cbe.org.eg/ar/monetary-policy" target="_blank">سياسة البنك المركزي النقدية</a></li>
                <li><a href="https://www.cbe.org.eg/ar/monetary-policy/mpc-meetings-schedule" target="_blank">لجنة السياسة النقدية</a></li>
                <li><a href="https://github.com/Al-QaTari/Bills-Calc" target="_blank">صفحة المشروع على GitHub</a></li>
            </ul>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
