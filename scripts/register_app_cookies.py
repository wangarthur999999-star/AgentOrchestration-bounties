"""Register GitHub App — use persistent Chrome profile, auto-click Google OAuth."""
import asyncio
import json
import os
import re
import urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright

MANIFEST_PATH = "C:/Users/wanga/OneDrive/Desktop/ai-projects/autogen-experiment/AgentOrchestration-bounties/scripts/github_app_manifest.json"
LOG_DIR = "C:/Users/wanga/OneDrive/Desktop/ai-projects/autogen-experiment/AgentOrchestration-bounties/logs"


async def click_when_visible(page, selectors: list[str], timeout: int = 3000):
    """Try multiple selectors, click first visible one."""
    await page.wait_for_timeout(timeout)
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                text = await btn.text_content()
                print(f"  Clicking: '{text.strip() if text else sel}'")
                await btn.click()
                return True
        except Exception:
            continue
    return False


async def main():
    print("=" * 60)
    print("  GitHub App Auto-Registration")
    print("=" * 60)

    with open(encoding='utf-8', MANIFEST_PATH) as f:
        manifest = json.load(f)
    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    user_data = str(Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data")

    async with async_playwright() as p:
        print(f"\nLaunching browser with Chrome profile...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        # Navigate to form. GitHub will redirect to login if sudo mode needed
        print(f"Navigating to pre-filled app form...")
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        url = page.url
        print(f"Current: {title}")
        print(f"URL: {url[:100]}...")

        # Check where we are
        if "settings/apps/new" in url and "login" not in url.lower():
            print("\n*** Already authenticated! Proceeding to create app. ***")
        elif "login" in url.lower():
            print("\n>>> SUDO MODE: GitHub requires re-authentication for settings. <<<")

            # Click "Continue with Google" to start OAuth
            google_btn_clicked = await click_when_visible(
                page,
                [
                    "button:has-text('Continue with Google')",
                    "a:has-text('Continue with Google')",
                    ".Button--secondary:has-text('Google')",
                ],
            )

            if google_btn_clicked:
                print("\n>>> Google OAuth started! Complete it in the browser window.")
                print(">>> After OAuth, GitHub will redirect to the app form.")
            else:
                print("\nCould not auto-click. Please click 'Continue with Google' manually.")

            # Wait for redirect to app settings page
            print("\nWaiting for app creation page...")
            for i in range(120):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps" in url and "login" not in url.lower():
                    print(f"\nApp form reached at t={i*2}s!")
                    break
                if i % 10 == 0 and i > 0:
                    loc = "Google OAuth" if "google.com" in url else ("GitHub Login" if "login" in url.lower() else "GitHub")
                    print(f"  [{i*2}s] On {loc}...")
            else:
                print("\nTimeout! Current state:")
                print(f"  URL: {page.url}")
                await page.screenshot(path=f"{LOG_DIR}/timeout_check.png", full_page=True)
                return

        # We should now be on the app form
        await page.wait_for_timeout(3000)
        title = await page.title()
        url = page.url
        print(f"\nApp Form - Title: {title}")
        print(f"App Form - URL: {url[:120]}")

        await page.screenshot(path=f"{LOG_DIR}/app_form.png", full_page=True)
        print("Screenshot saved: app_form.png")

        # Verify form content
        content = await page.content()
        if "CodeSage" in content:
            print("Form pre-filled with CodeSage AI Review values!")

        # Click Create GitHub App
        print("\nSubmitting form...")
        clicked = await click_when_visible(
            page,
            [
                "button:has-text('Create GitHub App')",
                "input[type='submit'][value*='Create']",
                "button[type='submit']",
            ],
            timeout=2000,
        )

        if not clicked:
            print("Auto-click failed. Searching for submit button manually...")
            buttons = page.locator("button")
            count = await buttons.count()
            for i in range(count):
                try:
                    btn = buttons.nth(i)
                    if not await btn.is_visible():
                        continue
                    text = (await btn.text_content() or "").strip()
                    if "create" in text.lower() and "app" in text.lower():
                        print(f"  Clicking button [{i}]: '{text}'")
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("ERROR: Could not click Create button")
            await page.screenshot(path=f"{LOG_DIR}/no_create_btn.png", full_page=True)
            return

        # Wait for creation result
        await page.wait_for_timeout(6000)
        final_url = page.url
        final_title = await page.title()
        print(f"\nResult: {final_title}")
        print(f"URL: {final_url}")

        await page.screenshot(path=f"{LOG_DIR}/creation_result.png", full_page=True)

        # Extract App ID
        content = await page.content()
        app_id_match = re.search(r"App\s*ID[:\s]*(\d+)", content, re.IGNORECASE)
        if app_id_match:
            app_id = app_id_match.group(1)
            print(f"\n*** APP ID: {app_id} ***")
            with open(encoding='utf-8', f"{LOG_DIR}/app_id.txt", "w") as f:
                f.write(app_id)

        # Generate private key
        gen_clicked = await click_when_visible(
            page,
            ["button:has-text('Generate a private key')", "button:has-text('Generate')"],
            timeout=3000,
        )
        if gen_clicked:
            await page.wait_for_timeout(3000)
            await page.screenshot(path=f"{LOG_DIR}/private_key.png", full_page=True)
            print("Private key generated! Saved to Downloads folder.")

        print("\n" + "=" * 60)
        print("Process complete! Keep the browser open.")
        print("1. Note the App ID")
        print("2. Download the private key (.pem file)")
        print("3. Install the app on your repositories")
        print("=" * 60)

        # Keep browser open for review
        await page.wait_for_timeout(120000)


if __name__ == "__main__":
    asyncio.run(main())
