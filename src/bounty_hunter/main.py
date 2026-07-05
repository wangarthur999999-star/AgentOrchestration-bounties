"""Bounty Hunter — Main pipeline orchestrator.

Workflow:
1. Scan all platforms for bounties
2. Filter for actionable (Python, USD, low competition)
3. Evaluate with AI (feasibility, confidence)
4. Rank by expected value (amount * confidence)
5. Generate solutions for top candidates
6. Report findings
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.bounty_hunter.scanner import BOUNTY_PLATFORMS, Bounty, BountyScanner
from src.bounty_hunter.solver import BountySolver, Solution

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("logs/bounties")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class BountyHunter:
    def __init__(
        self,
        deepseek_key: Optional[str] = None,
        apify_token: Optional[str] = None,
        min_amount: float = 50.0,
        max_competition: int = 10,
    ):
        self.deepseek_key = deepseek_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.apify_token = apify_token or os.environ.get("APIFY_TOKEN", "")
        self.min_amount = min_amount
        self.max_competition = max_competition

        self.scanner = BountyScanner(apify_token=self.apify_token)
        self.solver = BountySolver(
            api_key=self.deepseek_key,
            base_url="https://api.deepseek.com/v1",
        )

    async def close(self) -> None:
        await self.scanner.close()

    async def hunt(self, top_n: int = 5) -> list[dict]:
        """Run a full hunting cycle: scan → filter → evaluate → rank."""
        logger.info("=" * 50)
        logger.info(f"Bounty Hunt started at {datetime.now().isoformat()}")
        logger.info("=" * 50)

        logger.info("[1/4] Scanning platforms...")
        bounties = await self.scanner.scan_all()

        logger.info(f"[2/4] Filtering {len(bounties)} bounties...")
        actionable = self.scanner.filter_actionable(bounties)
        actionable = [b for b in actionable if b.amount_usd >= self.min_amount]
        actionable = [b for b in actionable if b.submissions_count <= self.max_competition]
        logger.info(f"  {len(actionable)} actionable after filters")

        if not actionable:
            logger.info("No actionable bounties found.")
            return []

        logger.info(f"[3/4] Evaluating top {min(top_n * 2, len(actionable))} candidates...")
        candidates = sorted(actionable, key=lambda b: b.amount_usd, reverse=True)
        candidates = candidates[: top_n * 2]

        evaluations = await self.solver.evaluate_batch(candidates)

        logger.info("[4/4] Ranking and reporting...")
        scored = []
        for bounty, solution in evaluations:
            if solution.feasible:
                expected_value = bounty.amount_usd * (solution.confidence / 100)
                scored.append({
                    "bounty": bounty,
                    "solution": solution,
                    "expected_value": expected_value,
                    "roi": expected_value / max(solution.estimated_hours, 0.5),
                })

        scored.sort(key=lambda x: x["expected_value"], reverse=True)
        top = scored[:top_n]

        self._save_report(top, len(bounties), len(actionable))

        for i, entry in enumerate(top):
            b = entry["bounty"]
            s = entry["solution"]
            logger.info(
                f"  #{i+1} {b.platform}: {b.title[:60]} "
                f"— ${b.amount_usd:.0f} (EV: ${entry['expected_value']:.0f}, "
                f"confidence: {s.confidence}%)"
            )

        return top

    def _save_report(self, results: list[dict], total: int, actionable: int) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = OUTPUT_DIR / f"hunt_{timestamp}.json"

        report = {
            "timestamp": datetime.now().isoformat(),
            "stats": {
                "total_scanned": total,
                "actionable": actionable,
                "feasible_candidates": len(results),
            },
            "candidates": [
                {
                    "rank": i + 1,
                    "platform": r["bounty"].platform,
                    "title": r["bounty"].title,
                    "amount_usd": r["bounty"].amount_usd,
                    "url": r["bounty"].url,
                    "confidence": r["solution"].confidence,
                    "expected_value": r["expected_value"],
                    "estimated_hours": r["solution"].estimated_hours,
                    "reasoning": r["solution"].reasoning,
                    "plan": r["solution"].plan,
                    "files": [
                        {"path": f["path"], "description": f.get("description", "")}
                        for f in r["solution"].files
                    ],
                }
                for i, r in enumerate(results)
            ],
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Report saved to {report_path}")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        logger.error("DEEPSEEK_API_KEY not set")
        return 1

    hunter = BountyHunter()
    try:
        results = await hunter.hunt(top_n=5)
        if results:
            logger.info(f"\nTop {len(results)} bounty candidates ready for action.")
        else:
            logger.info("No viable bounties found this cycle.")
    finally:
        await hunter.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
