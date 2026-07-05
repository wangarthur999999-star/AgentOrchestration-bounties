"""CodeSage configuration."""

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _get_private_key() -> str:
    """Load private key from env, supporting base64 or raw PEM."""
    raw = os.environ.get("CODESAGE_PRIVATE_KEY", "")
    if raw and not raw.startswith("-----BEGIN"):
        try:
            raw = base64.b64decode(raw).decode()
        except Exception:
            pass
    b64 = os.environ.get("CODESAGE_PRIVATE_KEY_BASE64", "")
    if b64:
        try:
            raw = base64.b64decode(b64).decode()
        except Exception:
            pass
    return raw


@dataclass
class CodeSageConfig:
    deepseek_api_key: str = field(default_factory=lambda: os.environ.get("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))
    github_app_id: str = field(default_factory=lambda: os.environ.get("CODESAGE_APP_ID", ""))
    github_webhook_secret: str = field(default_factory=lambda: os.environ.get("CODESAGE_WEBHOOK_SECRET", ""))
    github_private_key: str = field(default_factory=_get_private_key)

    review_model: str = "deepseek-chat"
    review_max_tokens: int = 4096
    review_temperature: float = 0.3

    max_files_per_review: int = 50
    max_diff_size: int = 100_000

    port: int = 8000
    host: str = "0.0.0.0"

    stripe_api_key: str = field(default_factory=lambda: os.environ.get("STRIPE_API_KEY", ""))
    pro_price_id: str = field(default_factory=lambda: os.environ.get("STRIPE_PRO_PRICE_ID", ""))

    def validate(self) -> list[str]:
        issues = []
        if not self.deepseek_api_key:
            issues.append("DEEPSEEK_API_KEY not set")
        if not self.github_token:
            issues.append("GITHUB_TOKEN not set")
        return issues
