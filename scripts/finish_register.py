"""Complete GitHub App registration — click Create, extract App ID, generate key."""
import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def screenshot(page, name, timeout=15000):
    """Take screenshot with timeout. Non-fatal on failure."""
    try:
        path = str(LOG_DIR / name)
        await page.screenshot(path=path, full_page=True, timeout=timeout)
        print(f"  Screenshot: {name}")
    except Exception as e:
        print(f"  Screenshot skipped ({name}): {e}")


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        context = contexts[0]
        pages = context.pages

        # Find the GitHub App creation page
        page = None
        for p in pages:
            try:
                url = p.url
                if "settings/apps" in url:
                    page = p
                    print(f"Found GitHub App page: {url[:100]}")
                    break
            except Exception:
                continue

        if not page:
            print("ERROR: No GitHub App page found. Re-navigating...")
            page = pages[0] if pages else await context.new_page()
            import urllib.parse
            encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
            form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"
            await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

        title = await page.title()
        url = page.url
        print(f"Page: {title}")
        print(f"URL: {url[:120]}")

        # Verify we're on the right page
        if "create" not in title.lower() and "settings/apps" not in url:
            print("ERROR: Not on the Create GitHub App page")
            await screenshot(page, "wrong_page.png")
            return 1

        await screenshot(page, "01_before_create.png")

        # === CLICK CREATE GITHUB APP ===
        print("\nLooking for 'Create GitHub App' button...")
        clicked = False

        # Strategy 1: Text match on buttons
        buttons = page.locator("button")
        count = await buttons.count()
        print(f"  Found {count} buttons on page")
        for i in range(count):
            try:
                btn = buttons.nth(i)
                if not await btn.is_visible():
                    continue
                text = (await btn.text_content() or "").strip()
                if not text:
                    continue
                print(f"  Button [{i}]: '{text[:80]}'")
                if "create" in text.lower() and "app" in text.lower():
                    print(f"  >>> Clicking button [{i}]: '{text}'")
                    await btn.click()
                    clicked = True
                    break
            except Exception as e:
                print(f"  Button [{i}] error: {e}")

        # Strategy 2: Submit inputs
        if not clicked:
            print("  Trying submit inputs...")
            submits = page.locator("input[type='submit']")
            sc = await submits.count()
            for i in range(sc):
                try:
                    s = submits.nth(i)
                    val = (await s.get_attribute("value") or "").lower()
                    if "create" in val:
                        print(f"  Clicking submit input [{i}]: value='{val}'")
                        await s.click()
                        clicked = True
                        break
                except Exception:
                    pass

        # Strategy 3: Form submit
        if not clicked:
            print("  Trying form submit...")
            forms = page.locator("form")
            fc = await forms.count()
            for i in range(fc):
                try:
                    form = forms.nth(i)
                    action = (await form.get_attribute("action") or "")
                    if "apps" in action or "new" in action:
                        print(f"  Submitting form [{i}]: action='{action}'")
                        await form.evaluate("f => f.submit()")
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("\nERROR: Could not click Create button!")
            await screenshot(page, "02_no_click.png")
            # Dump all clickable elements for debugging
            content = await page.content()
            (LOG_DIR / "page_debug.html").write_text(content, encoding="utf-8")
            print("  Saved page HTML for debugging")
            return 1

        # === WAIT FOR RESULT ===
        print("\nWaiting for creation result...")
        await page.wait_for_timeout(5000)

        # Wait for navigation away from the creation form
        for i in range(30):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()
            if "settings/apps/new" not in url:
                print(f"  Navigated away from form at t={(i+1)*2}s")
                break
            if i % 5 == 0:
                print(f"  [{i*2}s] Still on form...")
        else:
            print("  Warning: Still on form page after 60s")

        final_url = page.url
        final_title = await page.title()
        print(f"\nResult page: {final_title}")
        print(f"URL: {final_url[:150]}")

        await screenshot(page, "03_after_create.png")

        # === EXTRACT APP ID ===
        content = await page.content()
        app_id = None

        # Try multiple patterns
        patterns = [
            r"App\s*ID[:\s]*(\d+)",
            r"app_id[:\s]*(\d+)",
            r"App ID.*?(\d{4,})",
            r"<strong>(\d{5,})</strong>",
            r"client_id[:\s]*(\d+)",
        ]
        for pat in patterns:
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
            print(f"  Saved to logs/app_id.txt")
        else:
            print("\nCould not auto-extract App ID. Checking page text...")
            # Extract any numbers that look like IDs
            all_nums = re.findall(r'\b(\d{5,})\b', content)
            print(f"  Candidate numbers: {all_nums[:10]}")

        # === GENERATE PRIVATE KEY ===
        print("\nLooking for 'Generate a private key' button...")
        await page.wait_for_timeout(2000)

        gen_clicked = False
        buttons = page.locator("button")
        count = await buttons.count()
        for i in range(count):
            try:
                btn = buttons.nth(i)
                if not await btn.is_visible():
                    continue
                text = (await btn.text_content() or "").strip().lower()
                if "generate" in text and ("key" in text or "private" in text):
                    print(f"  Clicking: '{text}'")
                    await btn.click()
                    gen_clicked = True
                    await page.wait_for_timeout(3000)
                    await screenshot(page, "04_private_key.png")
                    print("  Private key should be downloading now!")
                    break
            except Exception:
                pass

        if not gen_clicked:
            print("  Generate button not found — check the browser manually.")
            print("  Look for: 'Generate a private key' button.")

        # === SAVE .ENV VALUES ===
        if app_id:
            env_path = Path(__file__).parent.parent / ".env"
            env_lines = []
            if env_path.exists():
                env_lines = env_path.read_text().splitlines()

            needed = {
                "GITHUB_APP_ID": app_id,
                "GITHUB_WEBHOOK_SECRET": manifest["hook_attributes"]["secret"],
            }

            new_lines = []
            existing_keys = set()
            for line in env_lines:
                key = line.split("=")[0].strip() if "=" in line else ""
                existing_keys.add(key)
                if key in needed:
                    new_lines.append(f"{key}={needed[key]}")
                    del needed[key]
                else:
                    new_lines.append(line)

            for key, val in needed.items():
                new_lines.append(f"{key}={val}")

            env_path.write_text("\n".join(new_lines) + "\n")
            print(f"\n  Updated .env with App ID and webhook secret")

        print("\n" + "=" * 60)
        print("REGISTRATION COMPLETE!")
        print(f"App ID: {app_id or 'Check browser'}")
        print("Check your Downloads folder for the .pem private key")
        print("=" * 60)

        await page.wait_for_timeout(10000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
