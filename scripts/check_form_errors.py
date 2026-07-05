"""Check current page for validation errors."""
import asyncio
import re
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        for page in browser.contexts[0].pages:
            if "settings/apps" not in page.url:
                continue

            url = page.url
            title = await page.title()
            print(f"Page: {title}")
            print(f"URL: {url[:150]}")

            # Check for error/alert elements
            errors = await page.locator(
                '[role=alert], .error, .flash-error, .flash, '
                '.FormControl-validation, .color-fg-danger, '
                '[class*=error], [class*=warning]'
            ).all()
            print("\nError/alert elements:")
            found = False
            for el in errors:
                try:
                    text = await el.text_content()
                    if text and text.strip():
                        cls = await el.get_attribute("class") or ""
                        print(f"  [{cls[:60]}]: {text.strip()[:200]}")
                        found = True
                except Exception:
                    pass
            if not found:
                print("  None found")

            # Check flash messages
            flashes = await page.locator(".flash, .flash-message, [class*=flash]").all()
            print("\nFlash messages:")
            for f in flashes:
                try:
                    text = await f.text_content()
                    if text and text.strip():
                        print(f"  {text.strip()[:200]}")
                except Exception:
                    pass

            # Search body text for error patterns
            body = await page.locator("body").text_content()
            print("\nError pattern search:")
            pats = [
                "already exists", "invalid", "required", "error",
                "failed", "must be", "cannot", "unavailable",
                "webhook", "ping", "callback", "url",
            ]
            for pat in pats:
                if pat in body.lower():
                    for m in re.finditer(pat, body, re.IGNORECASE):
                        start = max(0, m.start() - 40)
                        end = min(len(body), m.end() + 40)
                        snippet = body[start:end].replace("\n", " ")
                        print(f"  '{pat}': ...{snippet}...")

            # Take fresh screenshot
            await page.screenshot(
                path="C:/Users/wanga/OneDrive/Desktop/ai-projects/autogen-experiment/AgentOrchestration-bounties/logs/current_form.png",
                full_page=True,
                timeout=15000,
            )
            print("\nScreenshot saved: current_form.png")
            break


asyncio.run(check())
