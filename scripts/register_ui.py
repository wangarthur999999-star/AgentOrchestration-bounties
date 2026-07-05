"""Register GitHub App — proper Playwright UI interactions with action menus."""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def set_permission(page, resource_name, level):
    """Set a repository permission by interacting with the action-menu UI component.

    The permission UI has rows like:
      <li><strong>Pull requests</strong> ... <action-menu>...</action-menu></li>

    We need to:
    1. Find the row with matching <strong> text
    2. Click the action-menu trigger button within that row
    3. Click the radio menu item for the desired level
    """
    # Find the permission row by its strong label
    row = page.locator(f"li.Box-row:has(strong:text-is('{resource_name}'))")
    if await row.count() == 0:
        # Try broader match
        row = page.locator(f"li:has(strong:text-is('{resource_name}'))")

    if await row.count() == 0:
        print(f"  [WARN] No row found for '{resource_name}'")
        return False

    # Click the action-menu trigger within the row to open the dropdown
    # The trigger is typically a button or summary element inside action-menu
    trigger = row.locator("action-menu button, action-menu summary, action-menu [role='button']").first
    if await trigger.count() == 0:
        # Try clicking the whole action-menu area
        trigger = row.locator("action-menu").first

    if await trigger.count() == 0:
        print(f"  [WARN] No trigger found for '{resource_name}'")
        return False

    await trigger.click()
    await page.wait_for_timeout(500)

    # Now find and click the radio option
    # The menu items are <button role="menuitemradio" data-permission="<level>">
    level_label = {"read": "Read", "write": "Read & write", "none": "No access"}
    label = level_label.get(level, level)

    option = page.locator(f"button[role='menuitemradio'][data-permission='{level}'][data-resource='{resource_name.lower().replace(' ', '_')}']")
    if await option.count() > 0 and await option.is_visible():
        await option.click()
        print(f"  {resource_name} = {label}")
        await page.wait_for_timeout(300)
        return True

    # Fallback: find by visible text
    option = page.locator(f"button[role='menuitemradio']:has-text('{label}')")
    if await option.count() > 0:
        for i in range(await option.count()):
            opt = option.nth(i)
            if await opt.is_visible():
                await opt.click()
                print(f"  {resource_name} = {label} (fallback)")
                await page.wait_for_timeout(300)
                return True

    print(f"  [WARN] Could not find '{label}' option for '{resource_name}'")
    return False


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    webhook_url = manifest["hook_attributes"]["url"]
    webhook_secret = manifest["hook_attributes"]["secret"]

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to BLANK form
        print("Loading blank form...")
        await page.goto(
            "https://github.com/settings/apps/new",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        url = page.url
        title = await page.title()
        print(f"Page: {title}")

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

        # === FILL BASIC FIELDS ===
        print("\n=== Filling basic fields ===")

        # App name
        name_input = page.locator("input[name='integration[name]']")
        if await name_input.count() > 0:
            await name_input.fill("CodeSage AI Review")
            print("  Name filled")

        # Homepage URL
        url_input = page.locator("input[name='integration[url]']")
        if await url_input.count() > 0:
            await url_input.fill("https://github.com/wangarthur999999-star/AgentOrchestration-bounties")
            print("  URL filled")

        # Description
        desc_input = page.locator("textarea[name='integration[description]']")
        if await desc_input.count() > 0:
            await desc_input.fill("AI-powered code review that catches security vulnerabilities, bugs, and performance issues before they reach production. Powered by DeepSeek.")
            print("  Description filled")

        # Webhook URL
        wh_url = page.locator("input[name='integration[hook_attributes][url]']")
        if await wh_url.count() > 0:
            await wh_url.fill(webhook_url)
            print("  Webhook URL filled")

        # Webhook Secret
        wh_secret = page.locator("input[name='integration[hook_attributes][secret]']")
        if await wh_secret.count() > 0:
            await wh_secret.fill(webhook_secret)
            print("  Webhook secret filled")

        # === SSL VERIFICATION ===
        print("\n=== Setting SSL ===")
        ssl_enable = page.locator("#insecure_ssl_0")
        if await ssl_enable.count() > 0:
            await ssl_enable.check()
            print("  SSL ENABLED")

        # === SET PERMISSIONS ===
        print("\n=== Setting permissions via UI ===")
        await set_permission(page, "Pull requests", "write")
        await set_permission(page, "Contents", "read")

        # === CHECK EVENTS ===
        print("\n=== Setting events ===")
        await page.wait_for_timeout(1000)

        # After setting permissions, the pull_request checkbox should be enabled
        pr_cb = page.locator("input[type='checkbox'][value='pull_request']")
        if await pr_cb.count() > 0:
            # Check if it's still readonly
            is_readonly = await pr_cb.get_attribute("readonly")
            if is_readonly:
                print("  PR checkbox still readonly, forcing...")
                await page.evaluate("""
                    var cb = document.querySelector('input[value="pull_request"]');
                    if (cb) { cb.removeAttribute('readonly'); cb.disabled = false; cb.checked = true; }
                """)
            else:
                await pr_cb.check()
            print("  Pull request event checked")

        # === FIX PATH INPUTS ===
        await page.evaluate("""
            document.querySelectorAll('input[aria-label="Path"]').forEach(function(p) {
                p.value = '';
            });
        """)
        print("  Path inputs cleared")

        # === CHECK ERRORS ===
        await page.wait_for_timeout(2000)
        # Only check for VISIBLE errors
        visible_errors = page.locator(".flash-error:visible, .Banner--error:visible")
        err_count = await visible_errors.count()
        print(f"\n=== Visible errors: {err_count} ===")
        for i in range(min(err_count, 8)):
            try:
                t = await visible_errors.nth(i).text_content()
                if t and t.strip():
                    print(f"  - {t.strip()[:150]}")
            except Exception:
                pass

        # === SUBMIT ===
        print("\n=== Submitting ===")

        # Use the submit button
        submit_btn = page.locator("input[type='submit'][value*='Create']")
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            print("  Clicked Create GitHub App")
        else:
            # Try button
            create_btn = page.locator("button:has-text('Create GitHub App')")
            if await create_btn.count() > 0:
                await create_btn.first.click()
                print("  Clicked Create GitHub App button")
            else:
                print("  ERROR: No submit found!")
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
                errs = page.locator(".flash-error:visible, .Banner--error:visible")
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
                    if texts:
                        print(f"  [{i*2}s] Errors: {texts}")
                    else:
                        print(f"  [{i*2}s] Still on form...")
                else:
                    print(f"  [{i*2}s] Waiting... URL matches: {url[:60]}")
        else:
            print("\nTimeout!")
            errs = page.locator(".flash-error:visible, .Banner--error:visible")
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
        gen_btn = page.locator("button:has-text('Generate a private key')")
        if await gen_btn.count() > 0:
            await gen_btn.first.click()
            await page.wait_for_timeout(3000)
            print("  Check Downloads for .pem file")
        else:
            print("  Generate button not found — check browser")

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        await page.wait_for_timeout(15000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
