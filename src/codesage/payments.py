"""CodeSage payment processing — Stripe integration for Pro subscriptions."""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    user_id: str
    plan: str  # "free" | "pro"
    repos_limit: int
    reviews_per_month: int
    stripe_sub_id: Optional[str] = None
    status: str = "active"

    @property
    def can_review(self) -> bool:
        return self.status == "active"

    @staticmethod
    def free_tier(github_user_id: str) -> "Subscription":
        return Subscription(
            user_id=github_user_id,
            plan="free",
            repos_limit=1,
            reviews_per_month=5,
        )

    @staticmethod
    def pro_tier(github_user_id: str, stripe_sub_id: str) -> "Subscription":
        return Subscription(
            user_id=github_user_id,
            plan="pro",
            repos_limit=999,
            reviews_per_month=9999,
            stripe_sub_id=stripe_sub_id,
        )


class PaymentManager:
    """Manages subscriptions and billing.

    MVP implementation uses a simple in-memory store. Production should use a database.
    """

    def __init__(self):
        self._subscriptions: dict[str, Subscription] = {}
        self._monthly_usage: dict[str, int] = {}

    def get_subscription(self, github_user_id: str) -> Subscription:
        return self._subscriptions.get(
            github_user_id, Subscription.free_tier(github_user_id)
        )

    def set_subscription(self, sub: Subscription) -> None:
        self._subscriptions[sub.user_id] = sub

    def can_review(self, github_user_id: str, repo_name: str) -> bool:
        sub = self.get_subscription(github_user_id)
        if not sub.can_review:
            return False

        usage_key = f"{github_user_id}:{self._current_month()}"
        current = self._monthly_usage.get(usage_key, 0)
        return current < sub.reviews_per_month

    def record_review(self, github_user_id: str) -> None:
        usage_key = f"{github_user_id}:{self._current_month()}"
        self._monthly_usage[usage_key] = self._monthly_usage.get(usage_key, 0) + 1

    def _current_month(self) -> str:
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m")
