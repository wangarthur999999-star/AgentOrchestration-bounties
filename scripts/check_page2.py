"""Check page 2 (apps listing) for CodeSage."""
import asyncio
import re
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        pages = browser.contexts[0].pages

        # Find the page at /settings/apps (not /new)
        for i, page in enumerate(pages):
            url = page.url
            if "/settings/apps" in url and "new" not in url:
                print(f"Found apps page: {await page.title()}")
                print(f"URL: {url}")

                content = await page.content()

                # Search for CodeSage
                if "CodeSage" in content:
                    print("\n*** CodeSage found on page! ***")

                # Look for app name in the page
                # App listing typically shows app names and IDs
                body = await page.locator("body").text_content()

                # Search for app listing patterns
                lines = body.split("\n")
                for line in lines:
                    if "codesage" in line.lower():
                        print(f"  Line: {line.strip()[:120]}")
                    if "app id" in line.lower():
                        print(f"  ID line: {line.strip()[:120]}")

                # Click the first app link if it exists
                app_links = page.locator("a[href*='settings/apps/']")
                count = await app_links.count()
                print(f"\n{count} app links on page")
                for j in range(min(count, 15)):
                    try:
                        link = app_links.nth(j)
                        href = await link.get_attribute("href") or ""
                        text = (await link.text_content() or "").strip()
                        print(f"  [{j}] {text[:80]} -> {href[:100]}")
                    except Exception:
                        pass

                # Try to find and click on CodeSage app
                codesage_link = page.locator("a:has-text('CodeSage')")
                if await codesage_link.count() > 0:
                    print(f"\nClicking CodeSage link...")
                    await codesage_link.first.click()
                    await page.wait_for_timeout(3000)
                    new_url = page.url
                    new_title = await page.title()
                    print(f"Navigated to: {new_title}")
                    print(f"URL: {new_url}")

                    # Extract App ID
                    new_content = await page.content()
                    for m in re.findall(r"App\s*ID[:\s]*(\d+)", new_content, re.IGNORECASE):
                        print(f"*** APP ID: {m} ***")
                else:
                    print("\nNo CodeSage link found on apps page")
                    print("The app may not have been created.")

                break


asyncio.run(check())
