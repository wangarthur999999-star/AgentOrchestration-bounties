"""AI Review Engine — Multi-perspective code review using DeepSeek."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from src.codesage.config import CodeSageConfig

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """You are a senior code reviewer. Analyze the provided diff and find issues.
Focus on: security vulnerabilities, bugs, performance problems, maintainability issues, and style violations.

Output ONLY valid JSON with this exact structure:
{
  "summary": "One-line summary of the review",
  "issues": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "security|bug|performance|maintainability|style",
      "title": "Short issue title",
      "description": "Clear explanation of the problem",
      "suggestion": "How to fix it"
    }
  ],
  "praise": ["Good thing noticed"]
}

Rules:
- severity: CRITICAL for security/data-loss, HIGH for bugs, MEDIUM for maintainability, LOW for style
- line: best-guess line number in the NEW file, or null if can't determine
- Only report REAL issues, not nitpicks
- Max 10 issues total
- If the diff is trivial or has no issues, return empty issues array
"""

REVIEW_USER_TEMPLATE = """Review this pull request diff:

PR Title: {title}
Files Changed: {files_count}

{diff}
"""


@dataclass
class ReviewIssue:
    file: str
    line: Optional[int]
    severity: str
    category: str
    title: str
    description: str
    suggestion: str


@dataclass
class ReviewResult:
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)
    praise: list[str] = field(default_factory=list)
    raw_json: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "HIGH")

    def format_markdown(self) -> str:
        if not self.issues:
            return f"## AI Code Review\n\n{self.summary}\n\nNo issues found."

        lines = [
            "## AI Code Review",
            "",
            f"**{self.summary}**",
            "",
            f"| Severity | Count |",
            f"|----------|-------|",
            f"| CRITICAL | {self.critical_count} |",
            f"| HIGH | {self.high_count} |",
            f"| MEDIUM | {sum(1 for i in self.issues if i.severity == 'MEDIUM')} |",
            f"| LOW | {sum(1 for i in self.issues if i.severity == 'LOW')} |",
            "",
            "### Issues",
            "",
        ]

        for issue in sorted(self.issues, key=self._severity_sort_key):
            marker = {"CRITICAL": "[!]", "HIGH": "[H]", "MEDIUM": "[M]", "LOW": "[L]"}.get(issue.severity, "")
            file_loc = f"`{issue.file}`" + (f":{issue.line}" if issue.line else "")
            lines.append(f"**{marker} [{issue.severity}] {issue.title}**")
            lines.append(f"> {file_loc} — *{issue.category}*")
            lines.append(f"> {issue.description}")
            lines.append(f"> 💡 Suggestion: {issue.suggestion}")
            lines.append("")

        if self.praise:
            lines.append("### What Looks Good")
            for p in self.praise:
                lines.append(f"- {p}")

        lines.append("")
        lines.append("---")
        lines.append("*Automated review by [CodeSage](https://github.com/apps/codesage-ai)*")
        return "\n".join(lines)

    @staticmethod
    def _severity_sort_key(issue: ReviewIssue) -> int:
        return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(issue.severity, 4)


class ReviewEngine:
    def __init__(self, config: CodeSageConfig):
        self.config = config
        self._client = AsyncOpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
        )

    async def review_diff(
        self, diff: str, pr_title: str = "", files_count: int = 1
    ) -> ReviewResult:
        if not diff.strip():
            return ReviewResult(summary="No changes to review.")

        if len(diff) > self.config.max_diff_size:
            diff = diff[: self.config.max_diff_size] + "\n... (truncated)"

        user_prompt = REVIEW_USER_TEMPLATE.format(
            title=pr_title, files_count=files_count, diff=diff
        )

        try:
            response = await self._client.chat.completions.create(
                model=self.config.review_model,
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.config.review_max_tokens,
                temperature=self.config.review_temperature,
            )

            raw = response.choices[0].message.content or "{}"
            return self._parse_response(raw)

        except Exception as e:
            logger.error(f"Review engine error: {e}")
            return ReviewResult(summary=f"Review failed: {e}")

    async def review_files(
        self, files: list[dict], pr_title: str = ""
    ) -> ReviewResult:
        """Review multiple files by building a combined diff."""
        combined = []
        for f in files:
            filename = f.get("filename", "unknown")
            patch = f.get("patch", "")
            if patch:
                combined.append(f"--- a/{filename}\n+++ b/{filename}\n{patch}")

        if not combined:
            return ReviewResult(summary="No patch data available for review.")

        diff = "\n".join(combined)
        return await self.review_diff(diff, pr_title, len(files))

    def _parse_response(self, raw: str) -> ReviewResult:
        try:
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1])

            data = json.loads(raw)
            issues = [
                ReviewIssue(
                    file=i.get("file", ""),
                    line=i.get("line"),
                    severity=i.get("severity", "MEDIUM"),
                    category=i.get("category", "maintainability"),
                    title=i.get("title", "Issue"),
                    description=i.get("description", ""),
                    suggestion=i.get("suggestion", ""),
                )
                for i in data.get("issues", [])
            ]
            return ReviewResult(
                summary=data.get("summary", "Review complete."),
                issues=issues,
                praise=data.get("praise", []),
                raw_json=raw,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse review response: {e}")
            return ReviewResult(
                summary="Review completed but response parsing failed.",
                raw_json=raw,
            )
