"""Check current browser page state."""
import asyncio
import re
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        for page in browser.contexts[0].pages:
            url = page.url
            title = await page.title()
            print(f"Page: {title}")
            print(f"URL: {url}")

            content = await page.content()

            if "CodeSage" in content:
                print("CodeSage found in page content!")

            # Extract App ID
            for m in re.findall(r"App\s*ID[:\s]*(\d+)", content, re.IGNORECASE):
                print(f"App ID: {m}")

            # On apps listing, search for app links
            if "/settings/apps" in url and "new" not in url:
                # Check for links to specific apps
                links = page.locator("a[href*='settings/apps/']")
                count = await links.count()
                print(f"App links: {count}")
                for i in range(min(count, 10)):
                    try:
                        link = links.nth(i)
                        href = await link.get_attribute("href") or ""
                        text = (await link.text_content() or "").strip()
                        if "settings/apps/" in href:
                            print(f"  {text[:60]} -> {href}")
                    except Exception:
                        pass

            # Check if we're on a specific app page
            if "/settings/apps/" in url and "/settings/apps/new" not in url:
                print("On a specific app page!")
                body_text = await page.locator("body").text_content()
                # Find app ID patterns
                for m in re.findall(r"App ID[:\s]*(\d+)", body_text, re.IGNORECASE):
                    print(f"Found App ID in body: {m}")
                for m in re.findall(r"client_id[:\s]*(\d+)", body_text, re.IGNORECASE):
                    print(f"Found client_id: {m}")

            break


asyncio.run(check())
