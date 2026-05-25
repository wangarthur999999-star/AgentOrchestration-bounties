"""CodeSage webhook server — receives GitHub PR events and orchestrates reviews."""

import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from src.codesage.config import CodeSageConfig
from src.codesage.github_client import GitHubClient
from src.codesage.reviewer import ReviewEngine

logger = logging.getLogger(__name__)

config = CodeSageConfig()
review_engine = ReviewEngine(config)
review_queue: asyncio.Queue = asyncio.Queue()
github_client: Optional[GitHubClient] = None


def verify_signature(payload: bytes, signature: str) -> bool:
    if not config.github_webhook_secret:
        return True
    mac = hmac.new(
        config.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    )
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "queue_size": review_queue.qsize()})


async def webhook(request: Request) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature):
        return Response(status_code=401, content="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event not in ("pull_request", "ping"):
        return Response(status_code=200, content=f"Ignored event: {event}")

    if event == "ping":
        return JSONResponse({"message": "pong"})

    try:
        payload = await request.json()
        action = payload.get("action", "")

        if action not in ("opened", "synchronize", "reopened"):
            return JSONResponse({"message": f"Ignored action: {action}"})

        installation_id = payload.get("installation", {}).get("id")
        owner = payload.get("repository", {}).get("owner", {}).get("login", "")
        repo = payload.get("repository", {}).get("name", "")
        pr_number = payload.get("pull_request", {}).get("number")
        pr_title = payload.get("pull_request", {}).get("title", "")

        if not all([owner, repo, pr_number]):
            return JSONResponse({"error": "Missing PR info"}, status_code=400)

        logger.info(f"Queuing review for {owner}/{repo}#{pr_number}: {pr_title}")

        await review_queue.put({
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "pr_title": pr_title,
            "installation_id": installation_id,
        })

        return JSONResponse({"message": "Review queued", "pr": f"{owner}/{repo}#{pr_number}"})

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def process_reviews() -> None:
    """Background worker: process reviews from the queue."""
    global github_client

    if github_client is None:
        github_client = GitHubClient(config.github_token)

    while True:
        try:
            task = await review_queue.get()
            logger.info(
                f"Processing review: {task['owner']}/{task['repo']}#{task['pr_number']}"
            )

            pr_number = task["pr_number"]
            owner = task["owner"]
            repo = task["repo"]

            pr_info = await github_client.get_pr_info(owner, repo, pr_number)
            if not pr_info:
                logger.warning(f"Could not fetch PR info for {owner}/{repo}#{pr_number}")
                review_queue.task_done()
                continue

            files = await github_client.get_pr_files(owner, repo, pr_number)
            if not files:
                logger.info(f"No files to review for {owner}/{repo}#{pr_number}")
                review_queue.task_done()
                continue

            if len(files) > config.max_files_per_review:
                logger.info(
                    f"PR has {len(files)} files, limiting to {config.max_files_per_review}"
                )
                files = files[: config.max_files_per_review]

            result = await review_engine.review_files(files, task["pr_title"])

            markdown = result.format_markdown()
            await github_client.create_review(
                owner, repo, pr_number, markdown, event="COMMENT"
            )

            logger.info(
                f"Review posted for {owner}/{repo}#{pr_number}: "
                f"{result.critical_count}C/{result.high_count}H issues"
            )

            review_queue.task_done()

        except Exception as e:
            logger.error(f"Review processing error: {e}", exc_info=True)
            try:
                review_queue.task_done()
            except ValueError:
                pass


@asynccontextmanager
async def lifespan(app: Starlette):
    global github_client
    github_client = GitHubClient(config.github_token)
    worker = asyncio.create_task(process_reviews())
    logger.info("CodeSage server started")
    yield
    worker.cancel()
    if github_client:
        await github_client.close()
    logger.info("CodeSage server stopped")


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/webhook", webhook, methods=["POST"]),
]

app = Starlette(routes=routes, lifespan=lifespan)
