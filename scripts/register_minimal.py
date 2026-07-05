"""Register GitHub App — minimal manifest, fresh page, fast submit."""
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


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    # Build a CLEAN minimal manifest — avoid problematic fields
    clean_manifest = {
        "name": manifest["name"],
        "url": manifest["url"],
        "hook_attributes": {
            "url": manifest["hook_attributes"]["url"],
            "secret": manifest["hook_attributes"]["secret"],
        },
        "description": manifest["description"],
        "public": False,
        "default_permissions": {
            "pull_requests": "write",
            "contents": "read",
        },
        "default_events": ["pull_request"],
    }
    encoded = urllib.parse.quote(json.dumps(clean_manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        # Use a NEW page (not a reused one with stale state)
        page = await context.new_page()

        # Navigate to manifest pre-filled form
        print("Loading manifest form on fresh page...")
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"Page: {title}")
        print(f"URL: {url[:120]}")

        # Handle auth
        if "login" in url.lower():
            print("\nNeed auth. Clicking Google OAuth...")
            google_btn = page.locator("button:has-text('Google')")
            if await google_btn.count() > 0:
                await google_btn.first.click()
            for i in range(150):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps" in url and "login" not in url.lower():
                    print(f"  Authenticated! t={i*2}s")
                    break
                if i % 20 == 0 and i > 0:
                    print(f"  [{i*2}s] On: {url[:80]}")
            else:
                print("Auth timeout")
                return 1

        await page.wait_for_timeout(2000)
        url = page.url
        title = await page.title()
        print(f"\nForm ready: {title}")

        # === ONLY fix SSL — the one thing we can easily fix ===
        print("\nFixing SSL...")
        try:
            ssl_enable = page.locator("#insecure_ssl_0")
            if await ssl_enable.count() > 0:
                await ssl_enable.check(timeout=5000)
                print("  SSL set to ENABLED")
        except Exception as e:
            print(f"  SSL fix: {e}")
            # Try JS fallback
            await page.evaluate("document.getElementById('insecure_ssl_0').checked = true")
            print("  SSL enabled via JS fallback")

        # Clear any path inputs that might be invalid
        await page.evaluate("""
            document.querySelectorAll('input[aria-label="Path"]').forEach(function(p) {
                p.value = '';
            });
        """)

        await page.wait_for_timeout(500)

        # === CHECK what the form state looks like ===
        # Get permission values (read from hidden inputs)
        perm_check = await page.evaluate("""
(function() {
    var pr = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    var co = document.querySelector('input[name="integration[default_permissions][contents]"]');
    return 'pull_requests=' + (pr ? pr.value : '?') + ' contents=' + (co ? co.value : '?');
})();
        """)
        print(f"  Permissions: {perm_check}")

        # Check events
        event_check = await page.evaluate("""
(function() {
    var cb = document.querySelector('input[value="pull_request"]');
    if (!cb) return 'checkbox not found';
    return 'checked=' + cb.checked + ' readonly=' + cb.readOnly + ' disabled=' + cb.disabled;
})();
        """)
        print(f"  PR event: {event_check}")

        # === SUBMIT IMMEDIATELY ===
        print("\n=== SUBMITTING ===")
        await page.evaluate("""
(function() {
    var submits = document.querySelectorAll('input[type="submit"]');
    for (var i = 0; i < submits.length; i++) {
        if (submits[i].value.toLowerCase().indexOf('create') > -1) {
            submits[i].click();
            return;
        }
    }
    // Fallback: form submit
    var forms = document.querySelectorAll('form');
    for (var j = 0; j < forms.length; j++) {
        if (forms[j].action.indexOf('apps') > -1) {
            forms[j].submit();
            return;
        }
    }
})();
        """)
        print("  Submitted!")

        # === WAIT ===
        print("\nWaiting...")
        await page.wait_for_timeout(5000)

        for i in range(90):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** NAVIGATED AWAY! {title} ***")
                print(f"URL: {url[:150]}")
                break

            if i % 15 == 0:
                # Check for visible errors
                errors = page.locator(".flash-error, .Banner--error")
                visible_texts = []
                for j in range(min(await errors.count(), 5)):
                    try:
                        el = errors.nth(j)
                        if await el.is_visible():
                            t = await el.text_content()
                            if t and t.strip():
                                visible_texts.append(t.strip()[:100])
                    except Exception:
                        pass
                if visible_texts:
                    print(f"  [{i*2}s] Visible errors: {visible_texts[:3]}")
                else:
                    print(f"  [{i*2}s] On form, no visible errors...")
        else:
            print("\nTimeout. Checking ALL errors (including hidden)...")
            errors = page.locator(".flash-error, .Banner--error, .error")
            for j in range(await errors.count()):
                try:
                    t = await errors.nth(j).text_content()
                    if t and t.strip():
                        print(f"  ERROR: {t.strip()[:200]}")
                except Exception:
                    pass

            # Check if any are actually visible
            print("\nVisible errors:")
            visible = page.locator(".flash-error:visible, .Banner--error:visible, .error:visible")
            for j in range(await visible.count()):
                try:
                    t = await visible.nth(j).text_content()
                    if t and t.strip():
                        print(f"  VISIBLE: {t.strip()[:200]}")
                except Exception:
                    pass

            return 1

        # === SUCCESS — EXTRACT INFO ===
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

        # Generate private key
        await page.wait_for_timeout(2000)
        gen_btn = page.locator("button:has-text('Generate a private key')")
        if await gen_btn.count() > 0:
            await gen_btn.first.click()
            await page.wait_for_timeout(3000)
            print("Private key generated — check Downloads")

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
