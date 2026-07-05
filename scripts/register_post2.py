"""Register GitHub App via POST manifest — the official documented approach."""
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

    # Build clean manifest
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
    manifest_json = json.dumps(clean_manifest, separators=(",", ":"))

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = await context.new_page()

        # First navigate to GitHub to ensure session is active
        print("Checking GitHub session...")
        await page.goto("https://github.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check if logged in
        logged_in = await page.evaluate("""
(function() {
    var meta = document.querySelector('meta[name="user-login"]');
    return meta ? meta.content : 'not logged in';
})();
        """)
        print(f"  Logged in as: {logged_in}")

        if logged_in == "not logged in":
            print("Need to log in. Clicking Google OAuth...")
            await page.goto("https://github.com/login", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            google_btn = page.locator("button:has-text('Google')")
            if await google_btn.count() > 0:
                await google_btn.first.click()
            for i in range(150):
                await page.wait_for_timeout(2000)
                url = page.url
                if "github.com" in url and "login" not in url.lower():
                    print(f"  Logged in! t={i*2}s")
                    break
                if i % 20 == 0 and i > 0:
                    print(f"  [{i*2}s] On: {url[:80]}")
            else:
                print("Login timeout")
                return 1

        # Now use JS to create a form and POST the manifest
        # This is the documented approach: POST manifest to create the app
        print("\nCreating app via POST manifest...")

        # Generate a state parameter
        import time
        state = f"codesage_{int(time.time() * 1000)}"

        await page.evaluate(f"""
(function() {{
    var manifestJson = {json.dumps(manifest_json)};

    // Create a form
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = 'https://github.com/settings/apps/new';
    form.acceptCharset = 'UTF-8';

    // Add manifest input
    var input = document.createElement('input');
    input.type = 'text';
    input.name = 'manifest';
    input.value = manifestJson;
    form.appendChild(input);

    // Add to page
    document.body.appendChild(form);

    // Submit
    form.submit();
}})();
        """)
        print("  POST submitted!")

        # Wait for result
        await page.wait_for_timeout(5000)
        print(f"\nInitial response: {await page.title()}")
        print(f"URL: {page.url[:150]}")

        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            # Check if we got to a success page (not the form)
            if "settings/apps/new" not in url and "settings/apps" in url:
                print(f"\n*** APP CREATED! {title} ***")
                print(f"URL: {url[:150]}")
                break

            if "settings/apps/new" in url:
                print(f"  [{i*2}s] On confirmation form...")

                # Check if this is the confirmation page (should show Create button)
                # Try to click Create on the confirmation form
                if i == 2:  # After a few seconds, try clicking Create
                    await page.evaluate("""
(function() {
    // Fix SSL
    var ssl0 = document.getElementById('insecure_ssl_0');
    if (ssl0) ssl0.checked = true;

    // Set permissions
    var inputs = document.querySelectorAll('input[type="hidden"]');
    inputs.forEach(function(inp) {
        if (inp.name === 'integration[default_permissions][pull_requests]') inp.value = 'write';
        if (inp.name === 'integration[default_permissions][contents]') inp.value = 'read';
    });

    // Clear paths
    document.querySelectorAll('input[aria-label="Path"]').forEach(function(p) { p.value = ''; });

    // Submit
    var submits = document.querySelectorAll('input[type="submit"]');
    for (var j = 0; j < submits.length; j++) {
        if (submits[j].value.indexOf('Create') > -1) {
            submits[j].click();
            return;
        }
    }
})();
                    """)
                    print(f"  [{i*2}s] Clicked Create on confirmation form")
            else:
                print(f"  [{i*2}s] On: {title} | {url[:100]}")

        url = page.url
        if "settings/apps/new" in url:
            print("\nStill on form. This is the confirmation page — need to click Create.")
            print("The POST manifest flow shows a confirmation form, not direct creation.")

            # Try one more time with all fixes
            print("\nFinal attempt with all fixes...")

            # Fix SSL via Playwright
            try:
                ssl = page.locator("#insecure_ssl_0")
                if await ssl.count() > 0:
                    await ssl.check()
                    print("  SSL enabled")
            except Exception:
                pass

            # Set permissions via hidden inputs
            await page.evaluate("""
(function() {
    document.querySelector('input[name="integration[default_permissions][pull_requests]"]').value = 'write';
    document.querySelector('input[name="integration[default_permissions][contents]"]').value = 'read';
})();
            """)

            # Direct form submit with all correct values
            await page.evaluate("""
(function() {
    var form = document.querySelector('form[action*="apps"]');
    if (form) {
        // Collect all form data and submit
        var fd = new FormData(form);
        fd.set('integration[default_permissions][pull_requests]', 'write');
        fd.set('integration[default_permissions][contents]', 'read');
        fd.set('integration[hook_attributes][insecure_ssl]', '0');

        // Submit via fetch to see the response
        fetch(form.action, {
            method: 'POST',
            body: fd,
            headers: {
                'Accept': 'text/html',
            }
        }).then(function(r) {
            console.log('Fetch response:', r.status, r.url);
        });
    }
})();
            """)

            # Also click the submit button
            submit = page.locator("input[type='submit'][value*='Create']")
            if await submit.count() > 0:
                await submit.first.click()
                print("  Clicked Create")

            for i in range(30):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps/new" not in url:
                    print(f"\n*** Navigation at t={i*2}s! {await page.title()} ***")
                    break
            else:
                print("Still stuck on form.")
                return 1

        # Extract App ID
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

        # Generate key
        await page.wait_for_timeout(2000)
        gen_btn = page.locator("button:has-text('Generate')")
        if await gen_btn.count() > 0:
            await gen_btn.first.click()
            await page.wait_for_timeout(3000)
            print("Private key generated")

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
