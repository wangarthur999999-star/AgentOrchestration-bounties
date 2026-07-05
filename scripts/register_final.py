"""Register GitHub App — set permissions via menu radio buttons, then submit."""
import asyncio
import json
import re
import sys
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def click_menuitem(page, resource, level):
    """Click a permission menu radio button.
    Permissions use <button role='menuitemradio'> inside action menus.
    We need to: 1) set the hidden input, 2) click the radio button,
    3) update aria-checked state.
    """
    # Set hidden input value
    hidden_selector = f'input[name="integration[default_permissions][{resource}]"]'
    await page.evaluate(f"""
(function() {{
    var inp = document.querySelector('{hidden_selector}');
    if (inp) {{
        inp.value = '{level}';
        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
    }}
}})();
    """)

    # Click the menu radio button
    btn_id = f"integration_permission_{resource}_{level}"
    btn = page.locator(f"#{btn_id}")
    if await btn.count() > 0:
        try:
            await btn.click()
            print(f"  Set {resource} = {level}")
        except Exception as e:
            print(f"  Click {btn_id}: {e} (trying force)")
            await btn.click(force=True)
            print(f"  Set {resource} = {level} (forced)")
    else:
        print(f"  Button #{btn_id} not found — trying JS click")
        await page.evaluate(f"""
(function() {{
    var btn = document.getElementById('{btn_id}');
    if (btn) btn.click();
}})();
        """)


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to manifest pre-filled form
        print("Loading manifest pre-filled form...")
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"Page: {title}")

        # Handle auth if needed
        if "login" in url.lower():
            print("\nNeed login. Clicking Google OAuth...")
            google_btn = page.locator("button:has-text('Google')")
            if await google_btn.count() > 0:
                await google_btn.first.click()
            for i in range(150):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps" in url and "login" not in url.lower():
                    print(f"  Authenticated! t={i*2}s")
                    break
            else:
                print("Timeout waiting for auth")
                return 1

        await page.wait_for_timeout(2000)

        # === FIX 1: Enable SSL verification ===
        print("\n=== Enabling SSL verification ===")
        enable_ssl = page.locator("#insecure_ssl_0")
        if await enable_ssl.count() > 0:
            await enable_ssl.check()
            print("  SSL verification ENABLED")

        # === FIX 2: Set permissions via menu radio buttons ===
        print("\n=== Setting permissions ===")

        # First, we need to open the permission menus and click the right options
        # The permission UI uses <action-menu> with <button role="menuitemradio">

        # For pull_requests: click the "Read & write" radio button
        await click_menuitem(page, "pull_requests", "write")

        # For contents: click the "Read" radio button
        await click_menuitem(page, "contents", "read")

        # === FIX 3: Enable the pull_request event checkbox ===
        print("\n=== Enabling pull_request event ===")
        await page.wait_for_timeout(1000)

        # After setting permissions, the event checkboxes should become enabled
        # but GitHub's JS might need a moment to update
        await page.evaluate("""
(function() {
    // Force-enable all pull_request event checkboxes
    var checkboxes = document.querySelectorAll('input[name="integration[default_events][]"]');
    checkboxes.forEach(function(cb) {
        if (cb.value.indexOf('pull_request') === 0) {
            cb.removeAttribute('readonly');
            cb.disabled = false;
        }
    });
    // Check the main pull_request event
    var prCb = document.querySelector('input[value="pull_request"]');
    if (prCb) {
        prCb.checked = true;
        prCb.dispatchEvent(new Event('change', {bubbles: true}));
    }
})();
        """)
        print("  pull_request event forced checked")

        # === FIX 4: Clear permission path inputs ===
        print("\n=== Clearing permission paths ===")
        await page.evaluate("""
(function() {
    document.querySelectorAll('input[aria-label="Path"]').forEach(function(inp) {
        inp.value = '';
        inp.dispatchEvent(new Event('change', {bubbles: true}));
    });
})();
        """)

        # === VERIFY STATE ===
        await page.wait_for_timeout(2000)
        print("\n=== Verification ===")

        # Check permissions
        pr_perm = await page.evaluate("""
(function() {
    var inp = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    return inp ? inp.value : 'NOT FOUND';
})();
        """)
        print(f"  pull_requests permission: {pr_perm}")

        contents_perm = await page.evaluate("""
(function() {
    var inp = document.querySelector('input[name="integration[default_permissions][contents]"]');
    return inp ? inp.value : 'NOT FOUND';
})();
        """)
        print(f"  contents permission: {contents_perm}")

        # Check event checkbox
        pr_event = await page.evaluate("""
(function() {
    var cb = document.querySelector('input[value="pull_request"]');
    if (!cb) return 'NOT FOUND';
    return 'checked=' + cb.checked + ' readonly=' + cb.readOnly + ' disabled=' + cb.disabled;
})();
        """)
        print(f"  pull_request event: {pr_event}")

        # Check SSL
        ssl = await page.evaluate("""
(function() {
    var ssl0 = document.getElementById('insecure_ssl_0');
    return ssl0 ? 'enabled=' + ssl0.checked : 'NOT FOUND';
})();
        """)
        print(f"  SSL verification: {ssl}")

        # Check remaining visible errors
        errors = page.locator(".flash-error, .Banner--error")
        err_count = await errors.count()
        if err_count > 0:
            print(f"\n  Form errors ({err_count}):")
            for i in range(min(err_count, 5)):
                try:
                    t = await errors.nth(i).text_content()
                    if t and t.strip():
                        print(f"    - {t.strip()[:120]}")
                except Exception:
                    pass

        # === SUBMIT ===
        print("\n=== SUBMITTING ===")
        clicked = False

        # Try submit input
        submits = page.locator("input[type='submit']")
        for i in range(await submits.count()):
            try:
                s = submits.nth(i)
                val = (await s.get_attribute("value") or "").lower()
                if "create" in val:
                    await s.click()
                    print(f"  Clicked submit: '{val}'")
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            # Try button
            buttons = page.locator("button")
            for i in range(await buttons.count()):
                try:
                    btn = buttons.nth(i)
                    text = (await btn.text_content() or "").strip().lower()
                    if "create" in text and "app" in text:
                        await btn.click()
                        print(f"  Clicked button: '{text[:80]}'")
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("ERROR: No submit button!")
            return 1

        # === WAIT FOR RESULT ===
        print("\nWaiting for creation...")
        await page.wait_for_timeout(5000)

        for i in range(90):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** CREATED! Page: {title} ***")
                print(f"URL: {url[:150]}")
                break

            if i % 15 == 0:
                errs = page.locator(".flash-error, .Banner--error")
                count = await errs.count()
                if count > 0:
                    texts = []
                    for j in range(min(count, 3)):
                        try:
                            t = await errs.nth(j).text_content()
                            if t and t.strip():
                                texts.append(t.strip()[:100])
                        except Exception:
                            pass
                    print(f"  [{i*2}s] Errors: {texts}")
                else:
                    print(f"  [{i*2}s] Waiting...")
        else:
            print("\nTimeout! Checking errors...")
            errs = page.locator(".flash-error, .Banner--error, .error")
            for j in range(await errs.count()):
                try:
                    t = await errs.nth(j).text_content()
                    if t and t.strip():
                        print(f"  ERROR: {t.strip()[:200]}")
                except Exception:
                    pass
            return 1

        # === EXTRACT APP ID ===
        content = await page.content()
        app_id = None
        for pat in [
            r"App\s*ID[:\s]*(\d+)",
            r"app_id[:\s]*(\d+)",
            r"App ID.*?(\d{4,})",
            r"<strong>(\d{5,})</strong>",
        ]:
            for m in re.findall(pat, content, re.IGNORECASE):
                n = int(m)
                if 50000 < n < 999999999:
                    app_id = str(n)
                    break
            if app_id:
                break

        if app_id:
            print(f"\n*** APP ID: {app_id} ***")
            (LOG_DIR / "app_id.txt").write_text(app_id)

        # === GENERATE PRIVATE KEY ===
        print("\nGenerating private key...")
        await page.wait_for_timeout(2000)
        gen_result = await page.evaluate("""
(function() {
    var buttons = document.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
        var text = (buttons[i].textContent || '').toLowerCase();
        if (text.indexOf('generate') > -1 && text.indexOf('key') > -1) {
            buttons[i].click();
            return 'clicked: ' + text.substring(0, 40);
        }
    }
    return 'not found';
})();
        """)
        print(f"  {gen_result}")
        if "clicked" in gen_result:
            await page.wait_for_timeout(3000)
            print("  Check Downloads folder for .pem file")

        # === SAVE TO .ENV ===
        if app_id:
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                lines = env_path.read_text().splitlines()
                new_lines = []
                has_id = False
                for line in lines:
                    if line.startswith("GITHUB_APP_ID="):
                        new_lines.append(f"GITHUB_APP_ID={app_id}")
                        has_id = True
                    elif line.startswith("GITHUB_WEBHOOK_SECRET="):
                        new_lines.append(line)
                    else:
                        new_lines.append(line)
                if not has_id:
                    new_lines.append(f"GITHUB_APP_ID={app_id}")
                if "GITHUB_WEBHOOK_SECRET=" not in "\n".join(lines):
                    new_lines.append(f"GITHUB_WEBHOOK_SECRET={manifest['hook_attributes']['secret']}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("Updated .env")

        print(f"\n*** App ID: {app_id or 'CHECK BROWSER'} ***")
        print("Check Downloads for .pem private key")
        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
