"""Tests for CodeSage review engine."""

import asyncio

from src.codesage.config import CodeSageConfig
from src.codesage.reviewer import ReviewEngine


SAMPLE_DIFF = """--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -10,6 +10,10 @@ def authenticate(username: str, password: str) -> dict | None:
     user = db.query("SELECT * FROM users WHERE username = '" + username + "'")
     if user and user["password"] == password:
         return {"token": generate_token(user["id"]), "role": user["role"]}
+    elif username == "admin" and password == "admin123":
+        return {"token": generate_token(0), "role": "admin"}
+    elif not username:
+        logging.info(f"Empty username attempt from {request.ip}")
     return None

--- a/src/api/routes.py
+++ b/src/api/routes.py
@@ -20,7 +20,7 @@ async def get_user(user_id: int):
     user = await db.fetch_user(user_id)
     if not user:
-        return {"error": "User not found"}
+        pass
     return {"data": user}


def test_auth():
    assert authenticate("test", "test") is not None
    # TODO: add more edge cases
    # FIXME: hardcoded test credentials should be removed
    # HACK: ignoring rate limit in tests for now
"""


def test_review_engine_real():
    """Integration test: sends a vulnerable diff to DeepSeek for review."""
    config = CodeSageConfig()
    if not config.deepseek_api_key:
        print("SKIP: No DeepSeek API key")
        return

    engine = ReviewEngine(config)
    result = asyncio.run(engine.review_diff(SAMPLE_DIFF, "Add login feature", 2))

    print(f"\nReview Summary: {result.summary}")
    print(f"Issues found: {len(result.issues)}")
    print(f"Critical: {result.critical_count}, High: {result.high_count}")
    print()

    for issue in result.issues:
        print(f"  [{issue.severity}] {issue.title} ({issue.file}:{issue.line})")
        print(f"    {issue.description}")

    print(f"\nPraise: {result.praise}")
    print(f"\nMarkdown output:\n{result.format_markdown()[:500]}...")

    # Verify SQL injection was caught
    assert len(result.issues) > 0, "Should find at least one issue"
    assert any("SQL" in i.title.upper() or "injection" in i.title.lower() for i in result.issues), \
        "Should catch SQL injection"


if __name__ == "__main__":
    test_review_engine_real()
