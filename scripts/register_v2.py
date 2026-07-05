"""Register GitHub App v2 — reload page, handle errors, click Create."""
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


async def find_and_click(page, text_pattern, timeout=2000):
    """Find a button by text pattern and click it."""
    await page.wait_for_timeout(timeout)
    buttons = page.locator("button")
    count = await buttons.count()
    for i in range(count):
        try:
            btn = buttons.nth(i)
            if not await btn.is_visible():
                continue
            t = (await btn.text_content() or "").strip()
            if text_pattern.lower() in t.lower():
                print(f"  Clicking: '{t[:80]}'")
                await btn.click()
                return True
        except Exception:
            pass
    return False


async def check_errors(page):
    """Check for form validation errors and return them."""
    errors = []
    elements = await page.locator(
        ".flash-error, .error, [role=alert], .FormControl-validation, "
        ".color-fg-danger, .Banner--error, .sub-permissions-error"
    ).all()
    for el in elements:
        try:
            text = await el.text_content()
            if text and text.strip():
                errors.append(text.strip()[:200])
        except Exception:
            pass
    return errors


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)
    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        # Find or create the right page
        target_page = None
        for pg in context.pages:
            try:
                if "settings/apps" in pg.url or "github.com" in pg.url:
                    target_page = pg
                    break
            except Exception:
                pass

        if not target_page:
            target_page = context.pages[0] if context.pages else await context.new_page()
        page = target_page

        # === STEP 1: Reload to fix stale session ===
        print("Reloading page to fix stale session...")
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"Page: {title}")
        print(f"URL: {url[:120]}")

        # Check if we need to login
        if "login" in url.lower():
            print("\n*** Need to log in! The session is expired. ***")
            print("Looking for 'Continue with Google' button...")
            google_clicked = await find_and_click(page, "Continue with Google")
            if google_clicked:
                print("Clicked Google OAuth — waiting for redirect...")
                for i in range(120):
                    await page.wait_for_timeout(2000)
                    url = page.url
                    if "settings/apps" in url and "login" not in url.lower():
                        print(f"  Reached form at t={i*2}s")
                        break
                    if i % 15 == 0 and i > 0:
                        print(f"  [{i*2}s] On: {url[:80]}")
                else:
                    print("Timeout waiting for login. Manual intervention needed.")
                    return 1
            else:
                print("Please log in manually, then the script will continue.")
                for i in range(120):
                    await page.wait_for_timeout(2000)
                    url = page.url
                    if "settings/apps" in url and "login" not in url.lower():
                        print(f"  Logged in at t={i*2}s")
                        break
                else:
                    print("Timeout waiting for login.")
                    return 1

        # === STEP 2: Check for errors on the form ===
        await page.wait_for_timeout(3000)
        url = page.url
        title = await page.title()
        print(f"\nForm loaded: {title}")

        errors = await check_errors(page)
        if errors:
            print(f"\nFound {len(errors)} error/warning elements:")
            unique = list(set(errors))
            for e in unique[:15]:
                print(f"  - {e[:150]}")
        else:
            print("No visible errors on form.")

        # === STEP 3: Take quick screenshot ===
        try:
            await page.screenshot(
                path=str(LOG_DIR / "form_before_submit.png"),
                full_page=True,
                timeout=10000,
            )
            print("Screenshot: form_before_submit.png")
        except Exception as e:
            print(f"Screenshot failed (non-fatal): {e}")

        # === STEP 4: Click Create GitHub App ===
        print("\n=== SUBMITTING FORM ===")
        clicked = await find_and_click(page, "Create GitHub App", timeout=1000)

        if not clicked:
            # Try submit input
            submits = page.locator("input[type='submit']")
            sc = await submits.count()
            for i in range(sc):
                try:
                    s = submits.nth(i)
                    val = (await s.get_attribute("value") or "").lower()
                    if "create" in val:
                        print(f"  Clicking submit input: '{val}'")
                        await s.click()
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("ERROR: Could not find Create button!")
            return 1

        # === STEP 5: Wait for result ===
        print("Waiting for creation to complete...")
        await page.wait_for_timeout(5000)

        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** Navigated away from form at t={i*2}s ***")
                print(f"New page: {title}")
                print(f"URL: {url[:150]}")
                break

            # Check for errors
            if i % 5 == 0:
                errors = await check_errors(page)
                errors = [e for e in errors if e.strip() and "cookie" not in e.lower()]
                if errors:
                    unique = list(set(errors))[:5]
                    print(f"  [{i*2}s] Errors on form: {unique}")
                else:
                    print(f"  [{i*2}s] Still on form, no errors visible...")
        else:
            print("Still on form after 120s. Checking for blocking errors...")
            errors = await check_errors(page)
            unique = list(set(errors))
            for e in unique[:10]:
                print(f"  ERROR: {e[:200]}")

            # Dump page content for debugging
            try:
                content = await page.content()
                (LOG_DIR / "form_debug.html").write_text(content, encoding="utf-8")
                print("  Saved form HTML to logs/form_debug.html")
            except Exception:
                pass
            return 1

        # === STEP 6: Extract App ID ===
        content = await page.content()
        app_id = None
        for pat in [
            r"App\s*ID[:\s]*(\d+)",
            r"app_id[:\s]*(\d+)",
            r"App ID.*?(\d{4,})",
            r"<strong>(\d{5,})</strong>",
            r"client_id[:\s]*(\d+)",
        ]:
            matches = re.findall(pat, content, re.IGNORECASE)
            for m in matches:
                n = int(m)
                if 50000 < n < 999999999:
                    app_id = str(n)
                    print(f"\n*** APP ID: {app_id} ***")
                    break
            if app_id:
                break

        if app_id:
            (LOG_DIR / "app_id.txt").write_text(app_id)
            print("  Saved to logs/app_id.txt")

            # Update .env
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                env_text = env_path.read_text()
                new_lines = []
                for line in env_text.splitlines():
                    if line.startswith("GITHUB_APP_ID="):
                        new_lines.append(f"GITHUB_APP_ID={app_id}")
                    elif line.startswith("GITHUB_WEBHOOK_SECRET="):
                        new_lines.append(f"GITHUB_WEBHOOK_SECRET={manifest['hook_attributes']['secret']}")
                    else:
                        new_lines.append(line)
                if "GITHUB_APP_ID=" not in env_text:
                    new_lines.append(f"GITHUB_APP_ID={app_id}")
                if "GITHUB_WEBHOOK_SECRET=" not in env_text:
                    new_lines.append(f"GITHUB_WEBHOOK_SECRET={manifest['hook_attributes']['secret']}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("  Updated .env")

        # === STEP 7: Generate private key ===
        print("\nGenerating private key...")
        await page.wait_for_timeout(2000)
        gen_clicked = await find_and_click(page, "Generate", timeout=1000)
        if gen_clicked:
            await page.wait_for_timeout(3000)
            print("Private key should be downloading! Check Downloads folder.")
        else:
            print("Look for 'Generate a private key' button in the browser.")

        # Final screenshot
        try:
            await page.screenshot(
                path=str(LOG_DIR / "final_result.png"),
                full_page=True,
                timeout=10000,
            )
        except Exception:
            pass

        print("\n" + "=" * 60)
        print("REGISTRATION PROCESS COMPLETE")
        print(f"App ID: {app_id or 'CHECK BROWSER'}")
        print("=" * 60)

        # Keep page alive for review
        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
