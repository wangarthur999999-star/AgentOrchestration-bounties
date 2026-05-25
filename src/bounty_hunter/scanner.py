"""Multi-platform bounty scanner.

Sources (ranked by payout reliability):
1. Algora — confirmed payouts, Stripe
2. Opire — new, large bounties, Stripe/crypto
3. Bountycaster — USDC instant payout on Base
4. Dework — USDC/DAI multi-chain, milestone-based
5. Gitcoin — $50M+ cumulative, grants + hackathons
6. Immunefi — security bounties, up to $500K
7. SuperteamDAO — Solana bounties, same-day USDC
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

BOUNTY_PLATFORMS = {
    "algora": "https://algora.io/api/bounties",
    "opire": "https://opire.dev/api/bounties",
    "bountycaster": "https://www.bountycaster.xyz/api/bounties",
    "dework": "https://api.dework.xyz/bounties",
    "gitcoin": "https://api.gitcoin.co/api/v1/bounties",
    "superteam": "https://earn.superteam.fun/api/bounties",
}


@dataclass
class Bounty:
    id: str
    title: str
    description: str = ""
    platform: str = ""
    amount_usd: float = 0.0
    currency: str = "USD"
    url: str = ""
    repo_url: str = ""
    tags: list[str] = field(default_factory=list)
    difficulty: str = "unknown"
    deadline: Optional[str] = None
    submissions_count: int = 0
    created_at: Optional[str] = None
    source_raw: dict = field(default_factory=dict)

    @property
    def is_accessible(self) -> bool:
        """Bounties with real USD/stablecoin payouts and accessible repos."""
        return self.amount_usd > 0 and self.currency in ("USD", "USDC", "USDT", "DAI")

    @property
    def is_python_relevant(self) -> bool:
        python_keywords = ["python", "py", "fastapi", "django", "flask", "pytest"]
        text = f"{self.title} {self.description} {' '.join(self.tags)}".lower()
        return any(kw in text for kw in python_keywords)


class BountyScanner:
    def __init__(self, apify_token: str = ""):
        self._client = httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "BountyHunter/1.0"})
        self.apify_token = apify_token
        self._sources = list(BOUNTY_PLATFORMS.keys())

    async def close(self) -> None:
        await self._client.aclose()

    async def scan_all(self, max_per_source: int = 20) -> list[Bounty]:
        """Scan all configured platforms in parallel."""
        tasks = [self._scan_source(name, url, max_per_source) for name, url in BOUNTY_PLATFORMS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_bounties = []
        for source_name, result in zip(BOUNTY_PLATFORMS.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Scan failed for {source_name}: {result}")
            else:
                all_bounties.extend(result)

        logger.info(f"Scanned {len(all_bounties)} bounties across {len(BOUNTY_PLATFORMS)} platforms")
        return sorted(all_bounties, key=lambda b: b.amount_usd, reverse=True)

    async def scan_python_bounties(self) -> list[Bounty]:
        """Scan and filter for Python/AI-relevant bounties."""
        all_bounties = await self.scan_all()
        python_bounties = [b for b in all_bounties if b.is_python_relevant]
        logger.info(f"Found {len(python_bounties)} Python-relevant bounties")
        return python_bounties

    async def _scan_source(self, name: str, url: str, max_count: int) -> list[Bounty]:
        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    items = data[:max_count]
                elif isinstance(data, dict):
                    items = data.get("bounties", data.get("results", []))[:max_count]
                else:
                    return []
                return [self._normalize(item, name) for item in items]
            elif response.status_code == 404:
                logger.debug(f"Source {name} returned 404, may need auth")
                return []
            else:
                logger.debug(f"Source {name} returned {response.status_code}")
                return []
        except Exception as e:
            logger.debug(f"Error scanning {name}: {e}")
            return []

    async def scan_apify_aggregated(self) -> list[Bounty]:
        """Use Apify's bounty aggregator for Algora + Dework + GitHub + Collaborators.build."""
        if not self.apify_token:
            logger.info("No Apify token — skipping aggregated scan")
            return []

        actor_id = "theaurora~bounty-aggregator"
        url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
        params = {"token": self.apify_token, "format": "json"}

        try:
            response = await self._client.post(url, params=params, json={})
            if response.status_code == 200:
                data = response.json()
                return [self._normalize_apify(item) for item in data]
            logger.warning(f"Apify returned {response.status_code}")
        except Exception as e:
            logger.warning(f"Apify scan failed: {e}")
        return []

    def _normalize_apify(self, item: dict) -> Bounty:
        return Bounty(
            id=item.get("id", ""),
            title=item.get("title", ""),
            description=item.get("description", ""),
            platform=item.get("source", "apify"),
            amount_usd=float(item.get("amount", 0)),
            currency=item.get("currency", "USD"),
            url=item.get("url", ""),
            repo_url=item.get("repo_url", ""),
            tags=item.get("tags", []),
            source_raw=item,
        )

    def _normalize(self, item: dict, platform: str) -> Bounty:
        return Bounty(
            id=str(item.get("id", item.get("_id", ""))),
            title=item.get("title", item.get("name", "")),
            description=item.get("description", item.get("body", "")),
            platform=platform,
            amount_usd=float(item.get("amount", item.get("reward", item.get("value", 0)))),
            currency=item.get("currency", "USD"),
            url=item.get("url", item.get("html_url", "")),
            repo_url=item.get("repo_url", item.get("repository_url", "")),
            tags=item.get("tags", item.get("labels", [])),
            difficulty=item.get("difficulty", "unknown"),
            deadline=item.get("deadline", item.get("expires_at")),
            submissions_count=int(item.get("submissions", item.get("submissions_count", 0))),
            created_at=item.get("created_at", item.get("createdAt")),
            source_raw=item,
        )

    def filter_actionable(self, bounties: list[Bounty]) -> list[Bounty]:
        """Filter for bounties we can realistically solve."""
        return [
            b for b in bounties
            if b.is_accessible
            and b.is_python_relevant
            and b.submissions_count < 10  # Not too competitive
            and b.difficulty in ("easy", "medium", "unknown")
        ]
