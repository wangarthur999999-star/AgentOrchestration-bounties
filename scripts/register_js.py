"""Register GitHub App — pure JS form state injection, then submit."""
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

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to BLANK form (no manifest pre-fill so no stale errors)
        print("Loading blank form...")
        await page.goto(
            "https://github.com/settings/apps/new",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()

        # Handle auth
        if "login" in url.lower():
            print("Need login. Clicking Google OAuth...")
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

        if "settings/apps/new" not in url:
            print(f"ERROR: Not on app creation page. URL: {url}")
            return 1

        await page.wait_for_timeout(2000)
        print(f"On form: {await page.title()}")

        # === FILL THE ENTIRE FORM VIA JS ===
        print("\n=== Injecting form state via JavaScript ===")
        webhook_url = manifest["hook_attributes"]["url"]
        webhook_secret = manifest["hook_attributes"]["secret"]

        result = await page.evaluate(f"""
(function() {{
    var results = [];

    // Helper: set input value by name
    function setVal(name, value) {{
        var inp = document.querySelector('input[name="' + name + '"]');
        if (!inp) {{
            inp = document.querySelector('textarea[name="' + name + '"]');
        }}
        if (inp) {{
            inp.value = value;
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            results.push('set ' + name + ' = ' + (value || '(empty)').substring(0, 50));
        }} else {{
            results.push('MISSING: ' + name);
        }}
    }}

    // Helper: set hidden permission value
    function setPerm(resource, level) {{
        var name = 'integration[default_permissions][' + resource + ']';
        var inp = document.querySelector('input[name="' + name + '"]');
        if (inp) {{
            inp.value = level;
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        // Also update the aria-checked on menu radio buttons
        var buttons = document.querySelectorAll('[data-resource="' + resource + '"]');
        buttons.forEach(function(btn) {{
            if (btn.getAttribute('data-permission') === level) {{
                btn.setAttribute('aria-checked', 'true');
            }} else {{
                btn.setAttribute('aria-checked', 'false');
            }}
        }});
        results.push('perm ' + resource + ' = ' + level);
    }}

    // === BASIC INFO ===
    setVal('integration[name]', 'CodeSage AI Review');
    setVal('integration[url]', 'https://github.com/wangarthur999999-star/AgentOrchestration-bounties');
    setVal('integration[description]', 'AI-powered code review that catches security vulnerabilities, bugs, and performance issues before they reach production. Powered by DeepSeek.');

    // === WEBHOOK ===
    setVal('integration[hook_attributes][url]', '{webhook_url}');
    setVal('integration[hook_attributes][secret]', '{webhook_secret}');

    // SSL: 0 = enabled, 1 = disabled
    var ssl0 = document.getElementById('insecure_ssl_0');
    var ssl1 = document.getElementById('insecure_ssl_1');
    if (ssl0) {{ ssl0.checked = true; }}
    if (ssl1) {{ ssl1.checked = false; }}
    setVal('integration[hook_attributes][insecure_ssl]', '0');
    results.push('ssl = enabled');

    // Hook active
    setVal('integration[hook_attributes][active]', 'true');

    // === VISIBILITY ===
    setVal('integration[visibility]', 'private');

    // === PERMISSIONS ===
    setPerm('pull_requests', 'write');
    setPerm('contents', 'read');

    // === EVENTS ===
    // Enable and check pull_request checkbox
    var prCb = document.querySelector('input[value="pull_request"]');
    if (prCb) {{
        prCb.removeAttribute('readonly');
        prCb.disabled = false;
        prCb.checked = true;
        prCb.dispatchEvent(new Event('change', {{bubbles: true}}));
        results.push('event pull_request: checked');
    }}

    // === CLEAR PATHS ===
    var pathInputs = document.querySelectorAll('input[aria-label="Path"]');
    pathInputs.forEach(function(inp) {{
        inp.value = '';
        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
    }});
    // Also clear single_file_paths
    var sfps = document.querySelectorAll('input[name="integration[single_file_paths][]"]');
    sfps.forEach(function(inp) {{
        if (inp.type === 'text') inp.value = '';
    }});
    results.push('paths cleared');

    return results.join('\\n');
}})();
        """)
        print(result)

        # === CHECK FOR ERRORS ===
        await page.wait_for_timeout(2000)
        errors = page.locator(".flash-error, .Banner--error")
        err_count = await errors.count()
        print(f"\n=== Form errors: {err_count} ===")
        for i in range(min(err_count, 10)):
            try:
                t = await errors.nth(i).text_content()
                if t and t.strip():
                    print(f"  - {t.strip()[:150]}")
            except Exception:
                pass

        # === SUBMIT ===
        print("\n=== Submitting ===")
        submitted = await page.evaluate("""
(function() {
    // Try to submit the form directly
    var forms = document.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
        if (forms[i].action.indexOf('apps') > -1 || forms[i].action.indexOf('settings') > -1) {
            forms[i].submit();
            return 'submitted form[' + i + '] action=' + forms[i].action.substring(0, 80);
        }
    }
    // Fallback: click submit button
    var submits = document.querySelectorAll('input[type="submit"]');
    for (var j = 0; j < submits.length; j++) {
        if (submits[j].value.toLowerCase().indexOf('create') > -1) {
            submits[j].click();
            return 'clicked submit: ' + submits[j].value;
        }
    }
    return 'no submit found';
})();
        """)
        print(f"  {submitted}")

        # === WAIT FOR RESULT ===
        print("\nWaiting for creation...")
        await page.wait_for_timeout(5000)

        for i in range(90):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** NAVIGATED AWAY! Page: {title} ***")
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
                                texts.append(t.strip()[:120])
                        except Exception:
                            pass
                    if texts:
                        print(f"  [{i*2}s] Errors: {texts}")
                    else:
                        print(f"  [{i*2}s] Still on form...")
                else:
                    print(f"  [{i*2}s] No errors, still on form...")
        else:
            print("\nTimeout!")
            errs = page.locator(".flash-error, .Banner--error, .error")
            for j in range(await errs.count()):
                try:
                    t = await errs.nth(j).text_content()
                    if t and t.strip():
                        print(f"  ERROR: {t.strip()[:200]}")
                except Exception:
                    pass

            # Try clicking submit button directly (not JS)
            try:
                btn = page.locator("input[type='submit'][value*='Create']")
                if await btn.count() > 0:
                    await btn.first.click()
                    print("  Clicked submit button via Playwright — waiting more...")
                    for i in range(30):
                        await page.wait_for_timeout(2000)
                        url = page.url
                        if "settings/apps/new" not in url:
                            print(f"\n*** Created! {await page.title()} ***")
                            break
            except Exception as e:
                print(f"  Submit click error: {e}")

            if "settings/apps/new" in page.url:
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
                for line in lines:
                    if line.startswith("GITHUB_APP_ID="):
                        new_lines.append(f"GITHUB_APP_ID={app_id}")
                        has_id = True
                    else:
                        new_lines.append(line)
                if not has_id:
                    new_lines.append(f"GITHUB_APP_ID={app_id}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("Updated .env")

        # === GENERATE PRIVATE KEY ===
        print("\nGenerating private key...")
        await page.wait_for_timeout(2000)
        await page.evaluate("""
(function() {
    var buttons = document.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
        var text = (buttons[i].textContent || '').toLowerCase();
        if (text.indexOf('generate') > -1 && text.indexOf('key') > -1) {
            buttons[i].click();
            break;
        }
    }
})();
        """)
        await page.wait_for_timeout(3000)
        print("Check Downloads for .pem file")

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        await page.wait_for_timeout(15000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
