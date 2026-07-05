"""Register GitHub App v3 — manually fill form fields, bypass manifest issues."""
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

APP_NAME = "CodeSage AI Review"
HOMEPAGE_URL = "https://github.com/wangarthur999999-star/AgentOrchestration-bounties"
WEBHOOK_URL = "https://96b208f66e01d9a3-186-179-163-60.serveousercontent.com/webhook"
WEBHOOK_SECRET = "f31fb8b42e71601d2529dad548df9a0a2c2eebcadc0fe836e5f11cd2e2f16ad1"
DESCRIPTION = "AI-powered code review that catches security vulnerabilities, bugs, and performance issues before they reach production. Powered by DeepSeek."


async def screenshot(page, name):
    try:
        path = str(LOG_DIR / name)
        await page.screenshot(path=path, full_page=True, timeout=10000)
        print(f"  Screenshot: {name}")
    except Exception as e:
        print(f"  Screenshot skipped ({name}): {e}")


async def fill_field(page, label_text, value, field_type="textbox"):
    """Fill a form field by its label text."""
    # Find the label, then find the associated input
    labels = page.locator("label")
    count = await labels.count()
    for i in range(count):
        try:
            label = labels.nth(i)
            text = (await label.text_content() or "").strip()
            if label_text.lower() in text.lower():
                # Find the input associated with this label
                for_id = await label.get_attribute("for")
                if for_id:
                    inp = page.locator(f"#{for_id}")
                    if await inp.count() > 0:
                        await inp.fill(value)
                        print(f"  Filled '{label_text[:30]}' = '{value[:60]}'")
                        return True
        except Exception:
            pass

    # Fallback: try common input patterns
    print(f"  [WARN] Could not find field for '{label_text}' via label, trying fallback...")
    return False


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        page = None
        for pg in context.pages:
            try:
                if "github.com" in pg.url:
                    page = pg
                    break
            except Exception:
                pass
        if not page:
            page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to BLANK form (no manifest pre-fill, to avoid manifest parsing errors)
        print("Navigating to blank GitHub App creation form...")
        await page.goto(
            "https://github.com/settings/apps/new",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"Page: {title}")
        print(f"URL: {url[:120]}")

        # Check for login redirect
        if "login" in url.lower():
            print("\nSession expired. Need to re-authenticate.")
            google_btn = page.locator("button:has-text('Continue with Google')")
            if await google_btn.count() > 0:
                await google_btn.first.click()
                print("Clicked Google OAuth. Waiting for redirect...")
                for i in range(120):
                    await page.wait_for_timeout(2000)
                    url = page.url
                    if "settings/apps" in url and "login" not in url.lower():
                        print(f"  Authenticated at t={i*2}s")
                        break
                else:
                    print("Timeout. Please log in manually.")
                    return 1

        if "settings/apps/new" not in url:
            print(f"ERROR: Not on app creation page. URL: {url}")
            return 1

        await page.wait_for_timeout(2000)

        # === FILL THE FORM ===
        print("\n=== Filling form fields ===")

        # 1. GitHub App Name
        name_input = page.locator("input[name*='name'], input#name, input[aria-label*='name' i]").first
        if await name_input.count() > 0 and await name_input.is_visible():
            await name_input.fill(APP_NAME)
            print(f"  Name: {APP_NAME}")

        # 2. Homepage URL
        url_input = page.locator("input[name*='url'], input#url, input[aria-label*='homepage' i]").first
        if await url_input.count() > 0 and await url_input.is_visible():
            await url_input.fill(HOMEPAGE_URL)
            print(f"  Homepage URL: {HOMEPAGE_URL}")

        # 3. Webhook URL
        webhook_input = page.locator("input[name*='hook'], input[name*='webhook_url'], input#webhook_url").first
        if await webhook_input.count() > 0 and await webhook_input.is_visible():
            await webhook_input.fill(WEBHOOK_URL)
            print(f"  Webhook URL: {WEBHOOK_URL}")

        # 4. Webhook Secret
        secret_input = page.locator("input[name*='secret'], input#webhook_secret, input[name*='hook_secret']").first
        if await secret_input.count() > 0 and await secret_input.is_visible():
            await secret_input.fill(WEBHOOK_SECRET)
            print(f"  Webhook Secret: [set]")

        # 5. Description
        desc_input = page.locator("textarea[name*='description'], textarea#description").first
        if await desc_input.count() > 0 and await desc_input.is_visible():
            await desc_input.fill(DESCRIPTION)
            print(f"  Description: [set]")

        await page.wait_for_timeout(1000)

        # === SET PERMISSIONS ===
        print("\n=== Setting permissions ===")

        # Find and set "Pull requests" permission to "Read & write"
        # GitHub App form has permission dropdowns
        # Look for permission rows and set them
        try:
            # The form typically has a grid of permission settings
            # Look for "Pull requests" label and its associated select/dropdown
            perm_sections = page.locator("details, .js-permission, .Box-row, [class*=permission]")
            pc = await perm_sections.count()
            print(f"  Found {pc} permission sections")
        except Exception:
            pass

        # Try to find permission selects by their name attribute
        perm_selects = page.locator("select[name*='permission']")
        ps_count = await perm_selects.count()
        print(f"  Found {ps_count} permission selects")

        for i in range(ps_count):
            try:
                sel = perm_selects.nth(i)
                name = await sel.get_attribute("name") or ""
                if "pull_request" in name.lower():
                    await sel.select_option("write")
                    print(f"  Set {name} = write")
                elif "content" in name.lower():
                    await sel.select_option("read")
                    print(f"  Set {name} = read")
            except Exception as e:
                print(f"  Permission select [{i}] error: {e}")

        # === SUBSCRIBE TO EVENTS ===
        print("\n=== Subscribing to events ===")
        # Find "Pull request" checkbox
        try:
            pr_checkbox = page.locator("input[type='checkbox'][value='pull_request']")
            if await pr_checkbox.count() > 0 and not await pr_checkbox.is_checked():
                await pr_checkbox.check()
                print("  Checked: pull_request event")
            elif await pr_checkbox.count() > 0:
                print("  pull_request already checked")
        except Exception as e:
            print(f"  pull_request checkbox: {e}")

        await screenshot(page, "v3_form_filled.png")

        # === SUBMIT ===
        print("\n=== Submitting form ===")
        clicked = False

        # Try submit input
        submits = page.locator("input[type='submit']")
        for i in range(await submits.count()):
            try:
                s = submits.nth(i)
                val = (await s.get_attribute("value") or "").lower()
                if "create" in val:
                    print(f"  Clicking submit: '{val}'")
                    await s.click()
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            buttons = page.locator("button")
            for i in range(await buttons.count()):
                try:
                    btn = buttons.nth(i)
                    text = (await btn.text_content() or "").strip().lower()
                    if "create" in text and "app" in text:
                        print(f"  Clicking button: '{text}'")
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("ERROR: Cannot find submit button")
            return 1

        # === WAIT FOR RESULT ===
        print("Waiting for creation result...")
        await page.wait_for_timeout(5000)

        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** Created! Navigated to: {title} ***")
                print(f"URL: {url[:150]}")
                break

            if i % 10 == 0:
                # Check for errors
                errors = page.locator(".flash-error, .error, [role=alert]")
                ec = await errors.count()
                if ec > 0:
                    texts = []
                    for j in range(min(ec, 5)):
                        try:
                            t = await errors.nth(j).text_content()
                            if t and t.strip():
                                texts.append(t.strip()[:100])
                        except Exception:
                            pass
                    print(f"  [{i*2}s] Errors: {texts}")
                else:
                    print(f"  [{i*2}s] Waiting... URL: {url[:80]}")
        else:
            print("Timed out waiting for creation.")
            await screenshot(page, "v3_timeout.png")
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
            matches = re.findall(pat, content, re.IGNORECASE)
            for m in matches:
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
        buttons = page.locator("button")
        for i in range(await buttons.count()):
            try:
                btn = buttons.nth(i)
                text = (await btn.text_content() or "").strip().lower()
                if "generate" in text and ("key" in text or "private" in text):
                    print(f"  Clicking: '{text}'")
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    break
            except Exception:
                pass

        await screenshot(page, "v3_final.png")
        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        print("Check Downloads folder for .pem private key")

        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
