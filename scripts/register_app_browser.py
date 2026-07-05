"""Wait for user to complete OAuth, then click Create on pre-filled GitHub App form."""
import asyncio
import json
import re
import urllib.parse
from playwright.async_api import async_playwright

MANIFEST_PATH = "C:/Users/wanga/OneDrive/Desktop/ai-projects/autogen-experiment/AgentOrchestration-bounties/scripts/github_app_manifest.json"
CDP_URL = "http://localhost:9222"
LOG_DIR = "C:/Users/wanga/OneDrive/Desktop/ai-projects/autogen-experiment/AgentOrchestration-bounties/logs"


async def main():
    with open(encoding='utf-8', MANIFEST_PATH) as f:
        manifest = json.load(f)

    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print("=" * 60)
        print("  GitHub App Auto-Registration")
        print("=" * 60)

        current_url = page.url
        current_title = await page.title()

        # Check if user already completed OAuth
        if "settings/apps" in current_url:
            print(f"\nAlready on GitHub App page: {current_url}")
        else:
            # Navigate to form - this triggers login redirect if needed
            print(f"\nNavigating to app form...")
            await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Check where we ended up
            url = page.url
            title = await page.title()

            if "google.com" in url:
                print("\n>>> GOOGLE AUTH REQUIRED <<<")
                print(">>> Please select your Google account and sign in.")
                print(">>> The Chrome window should show a Google sign-in page.")
                print(">>> After OAuth, GitHub will auto-redirect to the app form.\n")
            elif "login" in url.lower():
                print("\n>>> GITHUB LOGIN REQUIRED <<<")
                print(">>> Please sign into GitHub (use 'Sign in with Google').")
                print(">>> After login, we'll auto-fill the app form.\n")
            elif "settings/apps" in url:
                print("\nPre-filled form loaded!")
            else:
                print(f"\nUnexpected page: {url}")
                print("Waiting to see what happens...")

        # WAIT for the app creation page (max 5 minutes)
        print("Waiting for GitHub App creation page...")
        for i in range(150):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            # Check for the app creation page
            if "settings/apps/new" in url and "login" not in url.lower():
                print(f"\nApp creation page reached at t={i*2}s!")
                break

            # If still on Google/auth pages, keep waiting
            if i % 15 == 0 and i > 0:
                current = "Google" if "google.com" in url else ("GitHub Login" if "login" in url.lower() else url[:80])
                print(f"  [{i*2}s] On: {current}")

        else:
            print("\nTimeout. Current state:")
            print(f"  URL: {page.url}")
            await page.screenshot(path=f"{LOG_DIR}/timeout_state.png", full_page=True)
            return

        # We should now be on the app form page
        await page.wait_for_timeout(3000)
        title = await page.title()
        print(f"\nPage: {title}")
        print(f"URL: {page.url[:120]}")

        await page.screenshot(path=f"{LOG_DIR}/app_form_filled.png", full_page=True)
        print("Screenshot saved: app_form_filled.png")

        # Verify form is pre-filled
        content = await page.content()
        if "CodeSage" in content:
            print("Form is pre-filled with CodeSage AI Review!")

        # Find and click Create button
        print("\nLooking for Create button...")

        # Try multiple selectors
        found = False
        selectors = [
            "button:has-text('Create GitHub App')",
            "button:has-text('Create GitHub App') >> nth=0",
            "input[type='submit'][value*='Create']",
            "button[type='submit']",
        ]

        for sel in selectors:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                text = await btn.text_content()
                print(f"Found: '{text.strip()}' - clicking!")
                await btn.click()
                found = True
                break

        if not found:
            print("Searching all buttons on page...")
            buttons = page.locator("button")
            count = await buttons.count()
            for i in range(min(count, 20)):
                try:
                    btn = buttons.nth(i)
                    if not await btn.is_visible():
                        continue
                    text = (await btn.text_content() or "").strip()
                    classes = (await btn.get_attribute("class") or "")
                    name = (await btn.get_attribute("name") or "")
                    val = (await btn.get_attribute("value") or "")
                    print(f"  [{i}] text='{text}' class='{classes[:60]}' name='{name}' value='{val}'")

                    if "create" in text.lower() and "app" in text.lower():
                        print(f"  -> Clicking this one!")
                        await btn.click()
                        found = True
                        break
                except Exception:
                    pass

        if not found:
            print("ERROR: Could not find Create button")
            return

        # Wait for result
        await page.wait_for_timeout(6000)
        new_url = page.url
        new_title = await page.title()
        print(f"\nAfter submit:")
        print(f"  Title: {new_title}")
        print(f"  URL: {new_url}")

        await page.screenshot(path=f"{LOG_DIR}/post_creation.png", full_page=True)

        # Extract App ID from the settings page
        content = await page.content()

        # Various patterns for App ID
        for pattern in [
            r"App\s*ID[:\s]*(\d+)",
            r"app_id[:\s]*(\d+)",
            r"App ID.*?(\d{4,})",
            r"<strong>(\d+)</strong>",
        ]:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                app_id = match.group(1)
                print(f"\n*** APP ID: {app_id} ***")
                break

        # Look for private key section
        if "private key" in content.lower() or "generate" in content.lower():
            print("\n>>> NEXT: Generate a private key!")
            print(">>> Look for 'Generate a private key' button on the page.")

            gen_btn = page.locator("button:has-text('Generate a private key')")
            if await gen_btn.count() > 0 and await gen_btn.is_visible():
                print("Clicking Generate a private key...")
                await gen_btn.first.click()
                await page.wait_for_timeout(3000)

                await page.screenshot(path=f"{LOG_DIR}/private_key_generated.png", full_page=True)
                print("Private key should be downloaded. Check your Downloads folder.")
                print("The .pem file will be saved as: <app-name>.<date>.private-key.pem")

        print("\n" + "=" * 60)
        print("Registration complete! Check the browser window.")


if __name__ == "__main__":
    asyncio.run(main())
