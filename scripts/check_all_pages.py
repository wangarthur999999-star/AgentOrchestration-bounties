"""Check ALL browser pages."""
import asyncio
import re
from playwright.async_api import async_playwright


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        for ctx in browser.contexts:
            pages = ctx.pages
            print(f"Context pages: {len(pages)}")
            for i, page in enumerate(pages):
                try:
                    url = page.url
                    title = await page.title()
                    print(f"\n  Page {i}: {title}")
                    print(f"  URL: {url[:150]}")
                    print(f"  Type: {url.split('/')[-1][:30] if '/' in url else 'N/A'}")

                    # Check for app creation success
                    content = await page.content()
                    for m in re.findall(r"App\s*ID[:\s]*(\d+)", content, re.IGNORECASE):
                        print(f"  *** APP ID FOUND: {m} ***")

                    # Check if this is the app settings page (post-creation)
                    pattern = r"/settings/apps/([^/]+)$"
                    match = re.search(pattern, url)
                    if match and "new" not in url:
                        print(f"  >>> This is an app settings page: {match.group(1)}")
                        # Look for App ID
                        app_id_matches = re.findall(r"(\d{5,})", content)
                        for aid in app_id_matches:
                            if 50000 < int(aid) < 999999999:
                                print(f"  >>> Potential App ID: {aid}")

                except Exception as e:
                    print(f"\n  Page {i}: Error - {e}")


asyncio.run(check())
