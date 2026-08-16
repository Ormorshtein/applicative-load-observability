"""Verify fixed scroll container selector — collect h6 titles across all scroll positions."""
from playwright.sync_api import sync_playwright

FIND_MAX_SH = """
() => {
    const elements = document.querySelectorAll('.scrollbar-view');
    let best = null;
    for (const el of elements) {
        if (!best || el.scrollHeight > best.scrollHeight) best = el;
    }
    return best ? {scrollHeight: best.scrollHeight, clientHeight: best.clientHeight} : null;
}
"""

SCROLL_TO = """
(y) => {
    const elements = document.querySelectorAll('.scrollbar-view');
    let best = null;
    for (const el of elements) {
        if (!best || el.scrollHeight > best.scrollHeight) best = el;
    }
    if (best) best.scrollTop = y;
    return best ? best.scrollTop : -1;
}
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    page.goto("http://127.0.0.1:3000/login", wait_until="networkidle")
    page.fill("input[name=user]", "admin")
    page.fill("input[name=password]", "admin")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")

    page.goto("http://127.0.0.1:3000/d/alo-main?from=now-8h&to=now",
              wait_until="networkidle")
    page.wait_for_timeout(8_000)

    info = page.evaluate(FIND_MAX_SH)
    print(f"Best scrollContainer: scrollHeight={info['scrollHeight']} clientHeight={info['clientHeight']}")

    scroll_height = info["scrollHeight"]
    client_height = info["clientHeight"]
    step = max(client_height - 100, 800)

    all_titles: set[str] = set()
    y = 0

    while True:
        actual_y = page.evaluate(SCROLL_TO, y)
        page.wait_for_timeout(2_500)
        titles = set(page.locator("h6").all_inner_texts())
        new_titles = titles - all_titles
        all_titles |= titles
        print(f"y={y:5d} actual={actual_y}: {len(titles)} h6s, {len(new_titles)} new: {sorted(new_titles)}")

        if y >= scroll_height:
            break
        y = min(y + step, scroll_height)

    print(f"\nTotal accumulated: {len(all_titles)}")
    print(sorted(all_titles))
    browser.close()
