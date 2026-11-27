import pytest

try:
    import pytest_asyncio
    from playwright.async_api import async_playwright, expect
except ImportError:
    pytest.skip("تخطي test_ui_rtl.py لأن المكتبات غير مثبتة", allow_module_level=True)

STREAMLIT_APP_URL = "http://localhost:8501"


@pytest_asyncio.fixture
async def browser_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1300, "height": 1600})
        yield page
        await browser.close()


@pytest.mark.ui
@pytest.mark.asyncio
async def test_help_text_is_right_aligned_and_has_no_literal_stars(browser_page):
    page = browser_page
    await page.goto(STREAMLIT_APP_URL, timeout=30000)
    summary = page.locator("summary", has_text="ما هي أذون الخزانة؟").first
    await expect(summary).to_be_visible(timeout=30000)
    await summary.click()
    expander = page.locator("details", has=summary)
    body = expander.locator('[data-testid="stExpanderDetails"]')
    await expect(body).to_contain_text("كيف تعمل؟", timeout=10000)
    text = await body.inner_text()
    assert "**" not in text

    info = await page.evaluate("""() => {
            const d = [...document.querySelectorAll('details')].find(
                (x) => x.querySelector('summary').innerText.includes('ما هي أذون الخزانة')
            );
            const ul = d.querySelector('ul');
            const li = d.querySelector('li');
            const cs = (e) => getComputedStyle(e);
            return {
                ulDir: cs(ul).direction, ulAlign: cs(ul).textAlign,
                liAlign: cs(li).textAlign,
                ulPadStart: cs(ul).paddingInlineStart,
                liRight: li.getBoundingClientRect().right,
                ulRight: ul.getBoundingClientRect().right,
            };
        }""")
    assert info["ulDir"] == "rtl"
    assert info["ulAlign"] in ("right", "start")
    assert info["liAlign"] in ("right", "start")
    # the bullet lives in the list's start padding (right side in RTL), so the
    # item text ends exactly one padding away from the list's right edge
    pad = float(info["ulPadStart"].replace("px", ""))
    assert abs((info["ulRight"] - info["liRight"]) - pad) < 2
