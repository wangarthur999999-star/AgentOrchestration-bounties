"""GitHub API client for CodeSage — PR fetching, review posting, comment management."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str):
        self.token = token
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "CodeSage-AI-Reviewer",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> Optional[str]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = await self._client.get(url, headers={"Accept": "application/vnd.github.diff"})
        if response.status_code == 200:
            return response.text
        logger.warning(f"Failed to fetch PR diff: {response.status_code}")
        return None

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = await self._client.get(url)
        if response.status_code == 200:
            return response.json()
        return []

    async def get_pr_info(self, owner: str, repo: str, pr_number: int) -> Optional[dict]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = await self._client.get(url)
        if response.status_code == 200:
            return response.json()
        return None

    async def create_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: Optional[list[dict]] = None,
    ) -> Optional[dict]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments
        response = await self._client.post(url, json=payload)
        if response.status_code in (200, 201):
            return response.json()
        logger.warning(f"Failed to create review: {response.status_code} {response.text}")
        return None

    async def create_inline_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ) -> Optional[dict]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        payload = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": side,
        }
        response = await self._client.post(url, json=payload)
        if response.status_code in (200, 201):
            return response.json()
        logger.warning(f"Failed to create inline comment: {response.status_code}")
        return None

    async def get_commit_id(self, owner: str, repo: str, pr_number: int) -> Optional[str]:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        response = await self._client.get(url)
        if response.status_code == 200:
            commits = response.json()
            if commits:
                return commits[-1]["sha"]
        return None
