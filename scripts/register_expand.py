"""Register GitHub App — expand collapsed sections, set permissions, submit."""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def set_permission_via_ui(page, resource_name, level):
    """Set a permission by expanding sections and clicking action-menu items."""
    # The permission rows are inside <details> sections
    # We need to first make sure all sections are expanded
    # Then click the action-menu trigger for the specific permission row
    # Then select the desired level

    # First, expand ALL collapsed details sections
    await page.evaluate("""
(function() {
    document.querySelectorAll('details[aria-expanded="false"], details:not([open])').forEach(function(d) {
        var summary = d.querySelector('summary');
        if (summary) summary.click();
    });
})();
    """)
    await page.wait_for_timeout(1000)

    # Find the permission row and its action-menu trigger
    # The row is <li> with <strong>resource_name</strong> and an <action-menu>
    row = page.locator(f"li:has(strong:text-is('{resource_name}'))")
    if await row.count() == 0:
        print(f"  Row not found for '{resource_name}'")
        return False

    # Find the action-menu trigger button within this row
    trigger = row.locator("action-menu button, action-menu [role='button']").first
    if await trigger.count() == 0:
        print(f"  No trigger in row for '{resource_name}'")
        return False

    # Check visibility
    if not await trigger.is_visible():
        print(f"  Trigger for '{resource_name}' not visible even after expand")
        # Try force click
        await trigger.click(force=True)
    else:
        await trigger.click()

    await page.wait_for_timeout(800)

    # Now select the level from the dropdown
    resource_key = resource_name.lower().replace(" ", "_")
    option = page.locator(
        f"button[role='menuitemradio'][data-resource='{resource_key}']"
        f"[data-permission='{level}']"
    )
    if await option.count() > 0:
        try:
            await option.click(timeout=5000)
            print(f"  {resource_name} = {level}")
            await page.wait_for_timeout(300)
            return True
        except Exception:
            pass

    # Fallback: try clicking by ID
    btn_id = f"integration_permission_{resource_key}_{level}"
    option = page.locator(f"#{btn_id}")
    if await option.count() > 0:
        try:
            await option.click(force=True)
            print(f"  {resource_name} = {level} (force)")
            await page.wait_for_timeout(300)
            return True
        except Exception as e:
            print(f"  Force click failed: {e}")

    print(f"  Could not select '{level}' for '{resource_name}'")
    return False


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    webhook_url = manifest["hook_attributes"]["url"]
    webhook_secret = manifest["hook_attributes"]["secret"]

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = await context.new_page()

        # Navigate to BLANK form
        print("Loading blank form on fresh page...")
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
                    print(f"  Authenticated! t={i*2}s")
                    break
            else:
                print("Auth timeout")
                return 1

        if "settings/apps/new" not in url:
            print(f"ERROR: Not on form. URL: {url[:100]}")
            return 1

        print(f"Form ready: {await page.title()}")

        # === FILL BASIC FIELDS ===
        print("\n=== Filling fields ===")
        await page.locator("input[name='integration[name]']").fill("CodeSage AI Review")
        await page.locator("input[name='integration[url]']").fill("https://github.com/wangarthur999999-star/AgentOrchestration-bounties")
        await page.locator("textarea[name='integration[description]']").fill(
            "AI-powered code review that catches security vulnerabilities, bugs, and performance issues before they reach production. Powered by DeepSeek."
        )
        await page.locator("input[name='integration[hook_attributes][url]']").fill(webhook_url)
        await page.locator("input[name='integration[hook_attributes][secret]']").fill(webhook_secret)
        print("  All fields filled")

        # === SSL ===
        await page.locator("#insecure_ssl_0").check()
        print("  SSL enabled")

        # === EXPAND & SET PERMISSIONS ===
        print("\n=== Expanding sections & setting permissions ===")
        await set_permission_via_ui(page, "Pull requests", "write")
        await set_permission_via_ui(page, "Contents", "read")

        # === EVENTS ===
        print("\n=== Events ===")
        await page.wait_for_timeout(1000)
        # After setting permissions, the checkbox should be enabled
        # Let's check and force-check if needed
        pr_cb = page.locator("input[value='pull_request']")
        if await pr_cb.count() > 0:
            is_readonly = await pr_cb.get_attribute("readonly")
            print(f"  PR checkbox readonly={is_readonly}")
            if is_readonly:
                await page.evaluate("""
                    var cb = document.querySelector('input[value="pull_request"]');
                    cb.removeAttribute('readonly');
                    cb.disabled = false;
                    cb.checked = true;
                """)
                print("  Forced PR event checked via JS")
            else:
                await pr_cb.check()
                print("  PR event checked")

        # === VERIFY ===
        await page.wait_for_timeout(1000)
        perm_state = await page.evaluate("""
(function() {
    var pr = document.querySelector('input[name="integration[default_permissions][pull_requests]"]');
    var co = document.querySelector('input[name="integration[default_permissions][contents]"]');
    var cb = document.querySelector('input[value="pull_request"]');
    return 'pr_perm=' + (pr?pr.value:'?') +
           ' co_perm=' + (co?co.value:'?') +
           ' pr_event=' + (cb?cb.checked:'?');
})();
        """)
        print(f"\n  State: {perm_state}")

        # === SUBMIT ===
        print("\n=== SUBMIT ===")
        submit_btn = page.locator("input[type='submit'][value*='Create']")
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            print("  Clicked Create GitHub App")

        # === WAIT ===
        print("\nWaiting...")
        await page.wait_for_timeout(5000)

        for i in range(60):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()
            if "settings/apps/new" not in url:
                print(f"\n*** CREATED! {title} ***")
                print(f"URL: {url[:150]}")
                break
            if i % 10 == 0:
                print(f"  [{i*2}s] On form...")
        else:
            print("\nTimeout")
            errs = page.locator(".flash-error:visible, .Banner--error:visible")
            for j in range(await errs.count()):
                try:
                    t = await errs.nth(j).text_content()
                    if t and t.strip():
                        print(f"  VISIBLE: {t.strip()[:200]}")
                except Exception:
                    pass
            return 1

        # === EXTRACT ===
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
                new_lines = [l for l in lines if not l.startswith("GITHUB_APP_ID=")]
                new_lines.append(f"GITHUB_APP_ID={app_id}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("Updated .env")

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
