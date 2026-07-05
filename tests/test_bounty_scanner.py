"""Quick test: scan for real bounties on accessible platforms."""

import asyncio
import json
import os

from src.bounty_hunter.scanner import BountyScanner


async def scan_available_sources():
    scanner = BountyScanner()
    try:
        all_bounties = await scanner.scan_all(max_per_source=10)
        print(f"\nTotal bounties found: {len(all_bounties)}")
        print(f"Accessible (USD/stablecoin): {sum(1 for b in all_bounties if b.is_accessible)}")
        print(f"Python-relevant: {sum(1 for b in all_bounties if b.is_python_relevant)}")

        if all_bounties:
            print("\nTop 10 by amount:")
            for i, b in enumerate(sorted(all_bounties, key=lambda x: x.amount_usd, reverse=True)[:10], 1):
                print(f"  {i}. [{b.platform}] {b.title[:70]} — ${b.amount_usd:.2f} {b.currency}")

        actionable = scanner.filter_actionable(all_bounties)
        if actionable:
            print(f"\nActionable bounties ({len(actionable)}):")
            for b in actionable[:5]:
                print(f"  [{b.platform}] {b.title[:70]} — ${b.amount_usd:.0f}")
        else:
            print("\nNo actionable bounties found — all platforms returned empty or require auth.")

        # Also try Apify if token is set
        apify_token = os.environ.get("APIFY_TOKEN", "")
        if apify_token:
            print("\nTrying Apify aggregator...")
            apify_bounties = await scanner.scan_apify_aggregated()
            print(f"Apify found: {len(apify_bounties)} bounties")
            for b in apify_bounties[:5]:
                print(f"  [{b.platform}] {b.title[:70]} — ${b.amount_usd:.0f}")

    finally:
        await scanner.close()


if __name__ == "__main__":
    asyncio.run(scan_available_sources())
