"""Register GitHub App — expand sections, click via JS, set permissions properly."""
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

    webhook_url = manifest["hook_attributes"]["url"]
    webhook_secret = manifest["hook_attributes"]["secret"]

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = await context.new_page()

        # Navigate to blank form
        print("Loading blank form...")
        await page.goto(
            "https://github.com/settings/apps/new",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        url = page.url
        if "login" in url.lower():
            print("Need auth. Clicking Google OAuth...")
            google_btn = page.locator("button:has-text('Google')")
            if await google_btn.count() > 0:
                await google_btn.first.click()
            for i in range(150):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps" in url and "login" not in url.lower():
                    break
            else:
                print("Auth timeout")
                return 1

        print(f"Form: {await page.title()}")

        # === FILL FIELDS ===
        print("Filling fields...")
        await page.locator("input[name='integration[name]']").fill("CodeSage AI Review")
        await page.locator("input[name='integration[url]']").fill(
            "https://github.com/wangarthur999999-star/AgentOrchestration-bounties"
        )
        await page.locator("textarea[name='integration[description]']").fill(
            "AI-powered code review that catches security vulnerabilities, bugs, "
            "and performance issues before they reach production. Powered by DeepSeek."
        )
        await page.locator("input[name='integration[hook_attributes][url]']").fill(webhook_url)
        await page.locator("input[name='integration[hook_attributes][secret]']").fill(webhook_secret)

        # SSL
        await page.locator("#insecure_ssl_0").check()

        # === EXPAND ALL COLLAPSED SECTIONS ===
        print("Expanding all sections...")
        await page.evaluate("""
(function() {
    // Click all summary elements to expand sections
    document.querySelectorAll('details summary').forEach(function(s) {
        s.click();
    });
})();
        """)
        await page.wait_for_timeout(2000)

        # === SET PERMISSIONS VIA PURE JS ===
        # The action-menu buttons exist in DOM but are inside closed dropdowns
        # Use JS to directly click the trigger button, then click the option
        print("Setting permissions via JS...")
        result = await page.evaluate("""
(function() {
    var results = [];

    function clickPermission(resource, level) {
        // Find the action-menu trigger button for this resource
        // The button has class 'js-action-selection-list-menu-button'
        // and is inside an <action-menu> inside a <li> with matching <strong>
        var rows = document.querySelectorAll('li.Box-row, li.js-list-group-item');
        var found = false;

        rows.forEach(function(row) {
            var strong = row.querySelector('strong');
            if (!strong || strong.textContent.trim() !== resource) return;

            // Found the row — find and click the action-menu trigger
            var trigger = row.querySelector('action-menu button[aria-haspopup], action-menu [role="button"]');
            if (!trigger) {
                trigger = row.querySelector('action-menu button');
            }
            if (trigger) {
                trigger.click();
                found = true;

                // Wait a bit for the menu to open (setTimeout in JS)
                setTimeout(function() {
                    // Click the right radio option
                    var option = document.querySelector(
                        'button[role="menuitemradio"]' +
                        '[data-resource="' + resource.toLowerCase().replace(' ', '_') + '"]' +
                        '[data-permission="' + level + '"]'
                    );
                    if (option) {
                        option.click();
                        results.push(resource + ' = ' + level);
                    } else {
                        results.push(resource + ': option not found');
                    }
                }, 100);
            } else {
                results.push(resource + ': trigger not found');
            }
        });

        if (!found) results.push(resource + ': row not found');
    }

    clickPermission('Pull requests', 'write');
    clickPermission('Contents', 'read');

    return results.join(' | ');
})();
        """)
        print(f"  JS result: {result}")

        # Wait for async clicks to complete
        await page.wait_for_timeout(3000)

        # === CHECK STATE ===
        perm_state = await page.evaluate("""
(function() {
    var pr = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    var co = document.querySelector('input[name="integration[default_permissions][contents]"]');
    return 'pr=' + (pr?pr.value:'?') + ' co=' + (co?co.value:'?');
})();
        """)
        print(f"  Permission state: {perm_state}")

        # Force-set hidden inputs if they're still "none"
        if "pr=none" in perm_state or "co=none" in perm_state:
            print("  Permissions still none — force-setting hidden inputs...")
            await page.evaluate("""
(function() {
    var pr = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    if (pr) pr.value = 'write';
    var co = document.querySelector('input[name="integration[default_permissions][contents]"]');
    if (co) co.value = 'read';

    // Also set aria-checked on the menu radio buttons
    var prWrite = document.querySelector('[data-resource="pull_requests"][data-permission="write"]');
    if (prWrite) prWrite.setAttribute('aria-checked', 'true');
    var coRead = document.querySelector('[data-resource="contents"][data-permission="read"]');
    if (coRead) coRead.setAttribute('aria-checked', 'true');
})();
            """)

        # === ENABLE EVENTS ===
        await page.evaluate("""
(function() {
    var cb = document.querySelector('input[value="pull_request"]');
    if (cb) {
        cb.removeAttribute('readonly');
        cb.disabled = false;
        cb.checked = true;
        cb.dispatchEvent(new Event('change', {bubbles: true}));
    }
})();
        """)
        print("  PR event forced checked")

        # Clear paths
        await page.evaluate("""
            document.querySelectorAll('input[aria-label="Path"]').forEach(function(p) { p.value = ''; });
        """)

        # === FINAL CHECK ===
        final_state = await page.evaluate("""
(function() {
    var pr = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    var co = document.querySelector('input[name="integration[default_permissions][contents]"]');
    var cb = document.querySelector('input[value="pull_request"]');
    var ssl = document.getElementById('insecure_ssl_0');
    return 'pr_perm=' + (pr?pr.value:'?') +
           ' co_perm=' + (co?co.value:'?') +
           ' pr_checked=' + (cb?cb.checked:'?') +
           ' ssl=' + (ssl?ssl.checked:'?');
})();
        """)
        print(f"\n  Final state: {final_state}")

        # === SUBMIT ===
        print("\nSubmitting...")
        submit_btn = page.locator("input[type='submit'][value*='Create']")
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            print("  Clicked Create")

        # === WAIT ===
        await page.wait_for_timeout(5000)
        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()
            if "settings/apps/new" not in url:
                print(f"\n*** NAVIGATED! {title} ***")
                print(f"URL: {url[:150]}")

                # Extract App ID
                content = await page.content()
                for m in re.findall(r"App\s*ID[:\s]*(\d+)", content, re.IGNORECASE):
                    n = int(m)
                    if 50000 < n < 999999999:
                        print(f"*** APP ID: {m} ***")
                        (LOG_DIR / "app_id.txt").write_text(str(m))

                        env_path = Path(__file__).parent.parent / ".env"
                        if env_path.exists():
                            lines = env_path.read_text().splitlines()
                            lines = [l for l in lines if not l.startswith("GITHUB_APP_ID=")]
                            lines.append(f"GITHUB_APP_ID={m}")
                            env_path.write_text("\n".join(lines) + "\n")
                break

            if i % 10 == 0:
                print(f"  [{i*2}s] Waiting...")

        if "settings/apps/new" in page.url:
            print("\nStill on form. Checking visible errors...")
            errs = page.locator(".flash-error:visible, .Banner--error:visible")
            for j in range(await errs.count()):
                try:
                    t = await errs.nth(j).text_content()
                    if t and t.strip():
                        print(f"  VISIBLE: {t.strip()[:200]}")
                except Exception:
                    pass

            # Check if we have an "app already exists" type error
            body = await page.locator("body").text_content()
            if "already exists" in body.lower():
                print("\n*** APP ALREADY EXISTS! Check /settings/apps ***")

        await page.wait_for_timeout(15000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
