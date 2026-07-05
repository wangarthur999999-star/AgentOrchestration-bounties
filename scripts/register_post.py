"""Register GitHub App via POST manifest submission — the documented approach."""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    manifest_json = json.dumps(manifest, separators=(",", ":"))

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to a blank page first to avoid stale state
        print("Navigating to GitHub...")
        await page.goto("https://github.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)

        # Check if logged in
        url = page.url
        if "login" in url.lower():
            print("Not logged in. Need to authenticate first.")
            print("Please log in manually, then press Enter...")
            input()
            url = page.url

        # Use JavaScript to create and submit a POST form with the manifest
        # This is the documented manifest flow approach
        print("\nCreating POST form with manifest...")
        state = "codesage_" + str(int(asyncio.get_event_loop().time() * 1000))

        result = await page.evaluate("""
(function(manifestJson, state) {
    // Create form element
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = 'https://github.com/settings/apps/new?state=' + state;
    form.style.display = 'none';

    // Add manifest input
    var input = document.createElement('input');
    input.type = 'text';
    input.name = 'manifest';
    input.value = manifestJson;
    form.appendChild(input);

    // Add to page and submit
    document.body.appendChild(form);
    form.submit();
    return 'submitted POST to ' + form.action;
})(arguments[0], arguments[1]);
        """, manifest_json, state)
        print(f"  {result}")

        # Wait for the form page to load
        await page.wait_for_timeout(5000)

        for i in range(30):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()
            print(f"  [{i*2}s] Page: {title} | URL: {url[:100]}")

            if "settings/apps" in url and "new" in url:
                print(f"\nForm page reached at t={i*2}s")

                # Check for errors
                await page.wait_for_timeout(2000)
                errors = page.locator(".flash-error, .Banner--error, .error")
                err_count = await errors.count()
                if err_count > 0:
                    print(f"  Errors ({err_count}):")
                    for j in range(min(err_count, 8)):
                        try:
                            t = await errors.nth(j).text_content()
                            if t and t.strip():
                                print(f"    - {t.strip()[:150]}")
                        except Exception:
                            pass
                break

            if "settings/apps" in url and "new" not in url:
                print(f"\n*** App created! Page: {title} ***")
                print(f"URL: {url[:150]}")
                break

        # Check if we're on the app settings page (creation succeeded)
        url = page.url
        if "settings/apps/new" not in url and "settings/apps" in url:
            print("\n=== App created! Extracting details... ===")

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
                print(f"*** APP ID: {app_id} ***")
                (LOG_DIR / "app_id.txt").write_text(app_id)

            # Generate private key
            print("\nLooking for 'Generate a private key'...")
            await page.wait_for_timeout(2000)
            buttons = page.locator("button")
            for i in range(await buttons.count()):
                try:
                    btn = buttons.nth(i)
                    text = (await btn.text_content() or "").strip().lower()
                    if "generate" in text and "key" in text:
                        print(f"Clicking: '{text[:80]}'")
                        await btn.click()
                        await page.wait_for_timeout(3000)
                        print("Check Downloads for .pem file")
                        break
                except Exception:
                    pass

            print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
            await page.wait_for_timeout(30000)
            return 0

        # If still on the form page, try to fix and submit
        if "settings/apps/new" in url:
            print("\n=== Fixing form issues and submitting... ===")

            # Enable SSL
            await page.evaluate("""
(function() {
    var ssl = document.getElementById('insecure_ssl_0');
    if (ssl) { ssl.checked = true; }
})();
            """)

            # Fix permissions and events via JS
            await page.evaluate("""
(function() {
    // Set permission dropdowns
    var selects = document.querySelectorAll('select');
    selects.forEach(function(s) {
        if (s.name.indexOf('pull_requests') > -1) {
            s.value = 'write';
            s.dispatchEvent(new Event('change', {bubbles: true}));
        }
        if (s.name.indexOf('contents') > -1) {
            s.value = 'read';
            s.dispatchEvent(new Event('change', {bubbles: true}));
        }
    });
    // Force check pull_request event
    var cb = document.querySelector('input[value="pull_request"]');
    if (cb) {
        cb.removeAttribute('readonly');
        cb.disabled = false;
        cb.checked = true;
    }
    // Clear path inputs
    document.querySelectorAll('input[aria-label="Path"]').forEach(function(p) {
        p.value = '';
    });
})();
            """)
            await page.wait_for_timeout(1000)

            # Click Create
            await page.evaluate("""
(function() {
    var submits = document.querySelectorAll('input[type="submit"]');
    for (var i = 0; i < submits.length; i++) {
        if (submits[i].value.toLowerCase().indexOf('create') > -1) {
            submits[i].click();
            return;
        }
    }
})();
            """)
            print("  Clicked Create — waiting...")
            await page.wait_for_timeout(5000)

            for i in range(60):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps/new" not in url:
                    print(f"\n*** Created! Page: {await page.title()} ***")
                    print(f"URL: {url[:150]}")

                    # Extract App ID
                    content = await page.content()
                    app_id = None
                    for pat in [
                        r"App\s*ID[:\s]*(\d+)",
                        r"app_id[:\s]*(\d+)",
                        r"App ID.*?(\d{4,})",
                    ]:
                        for m in re.findall(pat, content, re.IGNORECASE):
                            n = int(m)
                            if 50000 < n < 999999999:
                                app_id = str(n)
                                break
                        if app_id:
                            break

                    if app_id:
                        print(f"*** APP ID: {app_id} ***")
                        (LOG_DIR / "app_id.txt").write_text(app_id)

                    # Generate key
                    await page.wait_for_timeout(2000)
                    await page.evaluate("""
(function() {
    var buttons = document.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
        if ((buttons[i].textContent || '').toLowerCase().indexOf('generate') > -1) {
            buttons[i].click();
            break;
        }
    }
})();
                    """)
                    await page.wait_for_timeout(3000)
                    print("Check Downloads for .pem")
                    print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
                    return 0

                if i % 10 == 0:
                    errs = page.locator(".flash-error, .Banner--error")
                    texts = []
                    for j in range(min(await errs.count(), 3)):
                        try:
                            t = await errs.nth(j).text_content()
                            if t and t.strip():
                                texts.append(t.strip()[:120])
                        except Exception:
                            pass
                    print(f"  [{i*2}s] {'Errors: ' + str(texts) if texts else 'waiting...'}")

        print("\nUnable to complete registration via automation.")
        print("The form has validation errors that need manual attention.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
