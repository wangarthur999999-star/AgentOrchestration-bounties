"""Register GitHub App v4 — fresh persistent Chrome profile, manual form fill."""
import asyncio
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

MANIFEST = Path(__file__).parent / "github_app_manifest.json"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

WEBHOOK_SECRET = "f31fb8b42e71601d2529dad548df9a0a2c2eebcadc0fe836e5f11cd2e2f16ad1"


async def main():
    with open(encoding='utf-8', MANIFEST) as f:
        manifest = json.load(f)

    encoded = urllib.parse.quote(json.dumps(manifest, separators=(",", ":")))
    form_url = f"https://github.com/settings/apps/new?manifest_flow=1&manifest={encoded}"

    user_data = str(Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data")

    async with async_playwright() as p:
        print("Launching fresh Chrome with user profile...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        # Navigate to manifest-pre-filled form
        print(f"Navigating to pre-filled form...")
        await page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        title = await page.title()
        url = page.url
        print(f"Page: {title}")
        print(f"URL: {url[:120]}")

        # Handle login if needed
        if "login" in url.lower():
            print("\nNeed to authenticate...")
            await page.wait_for_timeout(2000)

            # Check for Google login button
            google_btn = page.locator("button:has-text('Google')")
            if await google_btn.count() > 0:
                print("Clicking Google login...")
                await google_btn.first.click()

            print("Waiting for authentication (max 5 min)...")
            for i in range(150):
                await page.wait_for_timeout(2000)
                url = page.url
                if "settings/apps" in url and "login" not in url.lower():
                    print(f"  Authenticated! t={i*2}s")
                    break
                if "google.com" in url:
                    print(f"  [{i*2}s] On Google — select your account")
                elif i % 15 == 0:
                    print(f"  [{i*2}s] On: {url[:80]}")
            else:
                print("Timeout waiting for auth.")
                return 1

        # Wait for form to fully load
        await page.wait_for_timeout(3000)
        url = page.url
        title = await page.title()
        print(f"\nForm: {title}")

        # Check for errors
        errors = await page.locator(".flash-error, .Banner--error, .error").all()
        error_texts = []
        for e in errors:
            try:
                t = await e.text_content()
                if t and t.strip():
                    error_texts.append(t.strip()[:150])
            except Exception:
                pass

        if error_texts:
            print(f"\nErrors on form ({len(error_texts)}):")
            for e in list(set(error_texts))[:8]:
                print(f"  - {e}")

        # Screenshot
        try:
            await page.screenshot(
                path=str(LOG_DIR / "v4_form.png"), full_page=True, timeout=10000
            )
            print("Screenshot: v4_form.png")
        except Exception as e:
            print(f"Screenshot: {e}")

        # === CLICK CREATE ===
        print("\n=== Clicking Create ===")
        clicked = False

        # Try submit inputs first
        submits = page.locator("input[type='submit']")
        for i in range(await submits.count()):
            try:
                s = submits.nth(i)
                val = (await s.get_attribute("value") or "").lower()
                if "create" in val:
                    print(f"Clicking submit: '{val}'")
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
                        print(f"Clicking button: '{text[:80]}'")
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    pass

        if not clicked:
            print("ERROR: No create button found!")
            return 1

        # === WAIT FOR RESULT ===
        print("Waiting for result...")
        await page.wait_for_timeout(5000)

        for i in range(90):
            await page.wait_for_timeout(2000)
            url = page.url
            title = await page.title()

            if "settings/apps/new" not in url:
                print(f"\n*** Created! Page: {title} ***")
                print(f"URL: {url[:150]}")
                break

            if i % 10 == 0:
                # Check errors
                errs = await page.locator(".flash-error, .Banner--error").all()
                if errs:
                    texts = []
                    for e in errs[:3]:
                        try:
                            t = await e.text_content()
                            if t and t.strip():
                                texts.append(t.strip()[:100])
                        except Exception:
                            pass
                    print(f"  [{i*2}s] Errors: {texts[:3]}")
                else:
                    print(f"  [{i*2}s] Still waiting... URL: {url[:80]}")
        else:
            print("\nTimeout! Dumping page state...")
            errs = await page.locator(".flash-error, .Banner--error, .error").all()
            for e in errs:
                try:
                    t = await e.text_content()
                    if t and t.strip():
                        print(f"  ERROR: {t.strip()[:200]}")
                except Exception:
                    pass
            try:
                content = await page.content()
                (LOG_DIR / "v4_debug.html").write_text(content, encoding="utf-8")
                print("  Saved v4_debug.html")
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
                for line in lines:
                    if line.startswith("GITHUB_APP_ID="):
                        new_lines.append(f"GITHUB_APP_ID={app_id}")
                    else:
                        new_lines.append(line)
                if "GITHUB_APP_ID=" not in "\n".join(lines):
                    new_lines.append(f"GITHUB_APP_ID={app_id}")
                if "GITHUB_WEBHOOK_SECRET=" not in "\n".join(lines):
                    new_lines.append(f"GITHUB_WEBHOOK_SECRET={WEBHOOK_SECRET}")
                env_path.write_text("\n".join(new_lines) + "\n")
                print("Updated .env")

        # === GENERATE PRIVATE KEY ===
        print("\nGenerating private key...")
        buttons = page.locator("button")
        for i in range(await buttons.count()):
            try:
                btn = buttons.nth(i)
                text = (await btn.text_content() or "").strip().lower()
                if "generate" in text and "key" in text:
                    print(f"Clicking: '{text[:80]}'")
                    await btn.click()
                    await page.wait_for_timeout(3000)
                    print("Check Downloads for .pem file")
                    break
            except Exception:
                pass

        try:
            await page.screenshot(
                path=str(LOG_DIR / "v4_final.png"), full_page=True, timeout=10000
            )
        except Exception:
            pass

        print(f"\nApp ID: {app_id or 'CHECK BROWSER'}")
        print("Check Downloads for .pem private key")
        print("\nKeep this browser open! Next: Install the app on repos.")
        await page.wait_for_timeout(120000)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
