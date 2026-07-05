"""Extract App ID and generate private key from the app settings page."""
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")

        # Find the app settings page
        for ctx in browser.contexts:
            for page in ctx.pages:
                url = page.url
                if "/settings/apps/" in url and "new" not in url and "codesage" in url.lower():
                    print(f"Found app page: {url}")
                    title = await page.title()
                    print(f"Title: {title}")

                    content = await page.content()

                    # Extract App ID
                    app_id = None
                    for pat in [
                        r"App\s*ID[:\s]*(\d+)",
                        r"app_id[:\s]*(\d+)",
                        r"App ID.*?(\d{4,})",
                        r"<strong>(\d{5,})</strong>",
                        r"client_id[:\s]*(\d+)",
                    ]:
                        for m in re.findall(pat, content, re.IGNORECASE):
                            n = int(m)
                            if 50000 < n < 999999999:
                                app_id = str(n)
                                print(f"*** APP ID: {app_id} (matched: {pat})")
                                break
                        if app_id:
                            break

                    if not app_id:
                        # Try extracting from page text
                        body = await page.locator("body").text_content()
                        # Look for any 5-8 digit number near "ID"
                        for m in re.findall(r"(\d{5,8})", body):
                            # Check context around this number
                            idx = body.find(m)
                            context = body[max(0,idx-30):idx+30].lower()
                            if "id" in context or "app" in context:
                                n = int(m)
                                if 50000 < n < 999999999:
                                    app_id = str(n)
                                    print(f"*** APP ID from body: {app_id} (context: {context.strip()})")

                        if not app_id:
                            # Print any numbers that might be the ID
                            print("\nSearching for potential App IDs in body...")
                            for m in re.findall(r"\d{5,8}", body):
                                idx = body.find(m)
                                ctx_text = body[max(0,idx-50):idx+50].replace('\n',' ').strip()
                                print(f"  {m} → ...{ctx_text}...")

                    if app_id:
                        (LOG_DIR / "app_id.txt").write_text(app_id)
                        print(f"Saved App ID: {app_id}")

                        env_path = Path(__file__).parent.parent / ".env"
                        if env_path.exists():
                            lines = env_path.read_text().splitlines()
                            lines = [l for l in lines if not l.startswith("GITHUB_APP_ID=")]
                            lines.append(f"GITHUB_APP_ID={app_id}")
                            env_path.write_text("\n".join(lines) + "\n")
                            print("Updated .env with GITHUB_APP_ID")

                    # Generate private key
                    await page.wait_for_timeout(1000)
                    gen_btn = page.locator("button:has-text('Generate'), button:has-text('generate')")
                    count = await gen_btn.count()
                    print(f"\nGenerate buttons found: {count}")

                    for i in range(count):
                        try:
                            btn = gen_btn.nth(i)
                            text = await btn.text_content()
                            print(f"  Button [{i}]: '{text.strip()}'")
                        except Exception:
                            pass

                    # Click generate if available
                    gen_private_key = page.locator("button:has-text('Generate a private key')")
                    if await gen_private_key.count() > 0:
                        print("\nClicking 'Generate a private key'...")
                        await gen_private_key.first.click()
                        await page.wait_for_timeout(3000)
                        print("Private key generated — check browser downloads")
                    else:
                        print("\nNo 'Generate a private key' button found")
                        # The button text might be slightly different
                        # Try clicking any button with "Generate" text
                        for i in range(count):
                            try:
                                btn = gen_btn.nth(i)
                                btn_text = (await btn.text_content() or "").strip()
                                if "generate" in btn_text.lower():
                                    print(f"Clicking: '{btn_text}'")
                                    await btn.click()
                                    await page.wait_for_timeout(3000)
                                    print("Clicked generate button")
                                    break
                            except Exception as e:
                                print(f"Error: {e}")

                    return 0

        print("No app settings page found!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
