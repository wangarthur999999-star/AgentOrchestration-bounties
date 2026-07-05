"""Fix form errors on current page and submit."""
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

LOG_DIR = Path(__file__).parent.parent / "logs"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        page = None
        for pg in context.pages:
            try:
                if "settings/apps" in pg.url:
                    page = pg
                    break
            except Exception:
                pass

        if not page:
            print("No GitHub App page found!")
            return 1

        print(f"Page: {await page.title()}")
        print(f"URL: {page.url[:120]}")

        # === FIX ALL ISSUES WITH JS ===
        print("\n=== Fixing form issues ===")
        fix_result = await page.evaluate("""
(function() {
    const results = [];

    // 1. Enable SSL verification
    const sslEnable = document.getElementById('insecure_ssl_0');
    if (sslEnable) {
        sslEnable.checked = true;
        results.push('SSL: enabled');
    }

    // 2. Set permissions via select elements
    const selects = document.querySelectorAll('select');
    selects.forEach(function(s) {
        var name = s.name || '';
        if (name.indexOf('pull_requests') > -1) {
            s.value = 'write';
            s.dispatchEvent(new Event('change', {bubbles: true}));
            results.push('permission: pull_requests=write');
        }
        if (name.indexOf('contents') > -1) {
            s.value = 'read';
            s.dispatchEvent(new Event('change', {bubbles: true}));
            results.push('permission: contents=read');
        }
    });

    // 3. Force check pull_request event
    var prCb = document.querySelector('input[value="pull_request"]');
    if (prCb) {
        prCb.removeAttribute('readonly');
        prCb.disabled = false;
        prCb.checked = true;
        prCb.dispatchEvent(new Event('change', {bubbles: true}));
        results.push('event: pull_request checked');
    }

    // 4. Clear permission paths
    var pathInputs = document.querySelectorAll('input[aria-label="Path"]');
    pathInputs.forEach(function(inp) {
        inp.value = '';
        inp.dispatchEvent(new Event('change', {bubbles: true}));
    });
    results.push('paths: cleared ' + pathInputs.length + ' inputs');

    // 5. Verify name field
    var nameInput = document.querySelector('input[name*="name"]');
    results.push('name: ' + (nameInput ? nameInput.value.substring(0, 40) : 'not found'));

    // 6. Verify webhook URL
    var whInputs = document.querySelectorAll('input[name*="hook"]');
    whInputs.forEach(function(inp) {
        if (inp.name.indexOf('secret') === -1 && inp.name.indexOf('insecure') === -1) {
            results.push('webhook: ' + (inp.value ? inp.value.substring(0, 60) : 'empty'));
        }
    });

    return results.join(' | ');
})();
        """)
        print(f"  {fix_result}")

        # === CHECK REMAINING ERRORS ===
        await page.wait_for_timeout(2000)
        errors = page.locator(".flash-error, .Banner--error, .error")
        error_count = await errors.count()
        print(f"\n=== Errors after fixes: {error_count} ===")
        for i in range(min(error_count, 10)):
            try:
                t = await errors.nth(i).text_content()
                if t and t.strip():
                    print(f"  - {t.strip()[:150]}")
            except Exception:
                pass

        # === SUBMIT VIA JS ===
        print("\n=== Submitting ===")
        submit_result = await page.evaluate("""
(function() {
    var submits = document.querySelectorAll('input[type="submit"]');
    for (var i = 0; i < submits.length; i++) {
        if (submits[i].value.toLowerCase().indexOf('create') > -1) {
            submits[i].click();
            return 'clicked submit: ' + submits[i].value;
        }
    }
    var buttons = document.querySelectorAll('button');
    for (var j = 0; j < buttons.length; j++) {
        var text = buttons[j].textContent || '';
        if (text.toLowerCase().indexOf('create github app') > -1) {
            buttons[j].click();
            return 'clicked button';
        }
    }
    return 'no button found';
})();
        """)
        print(f"  {submit_result}")

        # === WAIT FOR RESULT ===
        print("Waiting for creation result...")
        await page.wait_for_timeout(5000)

        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** SUCCESS! Navigated to: {title} ***")
                print(f"URL: {url[:150]}")
                break

            if i % 10 == 0:
                err_count = await page.locator(".flash-error, .Banner--error").count()
                if err_count > 0:
                    texts = []
                    for j in range(min(err_count, 3)):
                        try:
                            t = await page.locator(".flash-error, .Banner--error").nth(j).text_content()
                            if t and t.strip():
                                texts.append(t.strip()[:120])
                        except Exception:
                            pass
                    print(f"  [{i*2}s] Errors: {texts}")
                else:
                    print(f"  [{i*2}s] No errors, still on form... URL matches: settings/apps/new={('settings/apps/new' in url)}")
        else:
            print("\nTimeout. Checking final state...")
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

            # Update .env
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                lines = env_path.read_text().splitlines()
                new_lines = []
                has_id = False
                has_secret = False
                for line in lines:
                    if line.startswith("GITHUB_APP_ID="):
                        new_lines.append(f"GITHUB_APP_ID={app_id}")
                        has_id = True
                    elif line.startswith("GITHUB_WEBHOOK_SECRET="):
                        new_lines.append(line)
                        has_secret = True
                    else:
                        new_lines.append(line)
                if not has_id:
                    new_lines.append(f"GITHUB_APP_ID={app_id}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("Updated .env with App ID")

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

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        await page.wait_for_timeout(15000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
