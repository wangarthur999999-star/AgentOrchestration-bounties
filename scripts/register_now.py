"""GitHub App registration — user selects Google account, script auto-completes."""
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
    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        context = contexts[0]
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print("=" * 60)
        print("  CodeSage GitHub App — Auto Registration")
        print("=" * 60)

        # Navigate to form
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        url = page.url
        title = await page.title()

        if "settings/apps/new" in url and "login" not in url.lower():
            print("\nAlready authenticated! Proceeding to create app.")
        else:
            print("\n" + "!" * 60)
            print("  PLEASE SELECT YOUR GITHUB-LINKED GOOGLE ACCOUNT")
            print("  The Chrome window shows a Google account picker.")
            print("  Pick the account tied to: wangarthur999999-star")
            print("  Then click through any OAuth consent screens.")
            print("!" * 60)

            # Try to click Google button if on login page
            if "login" in url.lower():
                google_btn = page.locator("button:has-text('Continue with Google')")
                if await google_btn.count() > 0:
                    await google_btn.first.click()
                    print("Clicked 'Continue with Google' for you.")

            print("\nWaiting... (watching URL for changes)")

            # Wait for app form (max 10 minutes)
            last_url = ""
            for i in range(300):
                await page.wait_for_timeout(2000)
                url = page.url
                title = await page.title()

                # Detect successful form load
                if "settings/apps/new" in url and "login" not in url.lower():
                    print(f"\n*** App form loaded! (t={i * 2}s)")
                    break

                # Show progress on URL changes
                if url != last_url:
                    short = url[:100]
                    if "google.com" in url:
                        where = "Google OAuth"
                    elif "github.com/login" in url:
                        where = "GitHub Login"
                    elif "github.com/settings" in url:
                        where = "GitHub Settings"
                    elif "github.com" in url:
                        where = f"GitHub ({title[:40]})"
                    else:
                        where = short

                    print(f"  [{i * 2}s] -> {where}")
                    last_url = url

                    # If on GitHub but not settings and not login, try navigating again
                    if (
                        "github.com" in url
                        and "login" not in url.lower()
                        and "settings" not in url
                    ):
                        # User logged in but landed on home page
                        print(f"     Logged in! Re-navigating to form...")
                        await page.goto(
                            form_url, wait_until="domcontentloaded", timeout=30000
                        )
                        await page.wait_for_timeout(2000)
            else:
                print(f"\nTimeout after 10 min. URL: {url}")
                await page.screenshot(path=str(LOG_DIR / "timeout.png"), full_page=True)
                return 1

        # === ON APP FORM ===
        await page.wait_for_timeout(3000)
        title = await page.title()
        url = page.url
        print(f"\nForm loaded!")
        print(f"  Title: {title}")
        print(f"  URL: {url[:120]}")

        await page.screenshot(path=str(LOG_DIR / "app_form.png"), full_page=True)

        # Verify pre-filled content
        content = await page.content()
        if "CodeSage" in content:
            print("  Form pre-filled with CodeSage AI Review!")

        # Click Create
        print("\nSubmitting form...")
        clicked = False

        # Look for Create button
        buttons = page.locator("button")
        count = await buttons.count()
        for i in range(count):
            try:
                btn = buttons.nth(i)
                if not await btn.is_visible():
                    continue
                text = (await btn.text_content() or "").strip().lower()
                val = (await btn.get_attribute("value") or "").lower()
                if ("create" in text and "app" in text) or "create" in val:
                    print(f"  Clicking: {text}")
                    await btn.click()
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            # Try submit inputs
            submits = page.locator("input[type='submit']")
            if await submits.count() > 0:
                await submits.first.click()
                clicked = True
                print("  Clicked submit input")

        if not clicked:
            print("  ERROR: Cannot find Create button")
            await page.screenshot(path=str(LOG_DIR / "no_button.png"), full_page=True)
            return 1

        # Wait for result
        await page.wait_for_timeout(6000)
        final_url = page.url
        final_title = await page.title()
        print(f"\nPost-submit: {final_title}")
        print(f"URL: {final_url[:150]}")

        await page.screenshot(path=str(LOG_DIR / "post_submit.png"), full_page=True)

        # Extract App ID
        content = await page.content()

        # Various extraction attempts
        app_id = None
        patterns = [
            r"App\s*ID[:\s]*(\d+)",
            r"id[:\s]*(\d{5,})",
            r"(\d{6,})",
        ]
        for p in patterns:
            matches = re.findall(p, content, re.IGNORECASE)
            for m in matches:
                n = int(m)
                if 50000 < n < 999999999:  # Realistic App ID range
                    app_id = str(n)
                    break
            if app_id:
                break

        if app_id:
            print(f"\n*** APP ID: {app_id} ***")
            (LOG_DIR / "app_id.txt").write_text(app_id)

        # Generate private key
        for i in range(count):
            try:
                btn = buttons.nth(i)
                text = (await btn.text_content() or "").strip()
                if "generate" in text.lower() and "key" in text.lower():
                    print(f"Generating private key...")
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    await page.screenshot(
                        path=str(LOG_DIR / "private_key.png"), full_page=True
                    )
                    print("Private key downloaded! Check Downloads folder.")
                    break
            except Exception:
                pass

        print("\n" + "=" * 60)
        print("DONE! Check the browser.")
        print("=" * 60)

        await page.wait_for_timeout(30000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
