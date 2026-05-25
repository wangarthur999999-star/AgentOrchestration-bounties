"""Code Review Team — 3-agent security + quality + performance review pipeline.

Agents:
- Security Reviewer: Finds vulnerabilities (SQLi, XSS, hardcoded secrets, etc.)
- Quality Reviewer: Checks correctness, error handling, edge cases
- Performance Reviewer: Identifies bottlenecks, inefficiencies

Usage:
    python main.py --file path/to/code.py
    python main.py --diff path/to/diff.patch
"""

import argparse
import asyncio
import os
import sys

from openai import AsyncOpenAI

SYSTEM_PROMPTS = {
    "security": """You are a senior application security engineer.
Analyze the code for: SQL injection, XSS, hardcoded secrets, unsafe crypto,
path traversal, authentication bypasses, CSRF, insecure deserialization.
Output JSON: {"issues": [{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "line": int,
"title": str, "description": str, "fix": str}], "score": "A+|A|B|C|D|F"}""",

    "quality": """You are a senior software engineer doing code review.
Analyze for: bugs, logic errors, null/undefined handling, race conditions,
incorrect error handling, missing edge cases, type safety issues.
Output JSON: {"issues": [{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "line": int,
"title": str, "description": str, "fix": str}], "score": "A+|A|B|C|D|F"}""",

    "performance": """You are a performance engineer.
Analyze for: N+1 queries, memory leaks, blocking I/O, missing caching,
inefficient algorithms, unnecessary allocations, missing pagination.
Output JSON: {"issues": [{"severity": "CRITICAL|HIGH|MEDIUM|LOW", "line": int,
"title": str, "description": str, "fix": str}], "score": "A+|A|B|C|D|F"}""",
}


class CodeReviewTeam:
    def __init__(self, api_key: str = "", base_url: str = "https://api.deepseek.com/v1"):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def review(self, code: str) -> dict:
        """Run all three review agents in parallel."""
        import json

        tasks = [
            self._run_agent(role, code) for role in ["security", "quality", "performance"]
        ]
        results = await asyncio.gather(*tasks)

        all_issues = []
        scores = {}
        for role, raw in zip(["security", "quality", "performance"], results):
            try:
                data = json.loads(raw)
                all_issues.extend(data.get("issues", []))
                scores[role] = data.get("score", "N/A")
            except json.JSONDecodeError:
                scores[role] = "PARSE_ERROR"

        critical = sum(1 for i in all_issues if i["severity"] == "CRITICAL")
        high = sum(1 for i in all_issues if i["severity"] == "HIGH")

        return {
            "issues": sorted(all_issues, key=lambda i: ["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(i["severity"])),
            "scores": scores,
            "summary": f"Found {len(all_issues)} issues: {critical} critical, {high} high",
            "verdict": "REJECT" if critical > 0 else ("WARN" if high > 0 else "APPROVE"),
        }

    async def _run_agent(self, role: str, code: str) -> str:
        response = await self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPTS[role]},
                {"role": "user", "content": f"Review this code:\n\n```\n{code[:15000]}\n```"},
            ],
            max_tokens=2048,
            temperature=0.2,
        )
        return response.choices[0].message.content or "{}"

    def format_report(self, result: dict) -> str:
        lines = [
            "=" * 60,
            "  CODE REVIEW REPORT",
            "=" * 60,
            "",
            f"Verdict: {result['verdict']}",
            f"Summary: {result['summary']}",
            "",
            "Scores by Category:",
        ]
        for role, score in result["scores"].items():
            lines.append(f"  {role.capitalize()}: {score}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("ISSUES")
        lines.append("-" * 60)

        for i, issue in enumerate(result["issues"], 1):
            sev = issue["severity"]
            lines.append(f"\n{i}. [{sev}] {issue['title']} (line {issue.get('line', '?' )})")
            lines.append(f"   {issue['description']}")
            lines.append(f"   Fix: {issue['fix']}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="AI Code Review Team")
    parser.add_argument("--file", help="Path to Python file to review")
    parser.add_argument("--diff", help="Path to diff/patch file to review")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            code = f.read()
    elif args.diff:
        with open(args.diff, encoding="utf-8") as f:
            code = f.read()
    else:
        print("Reading from stdin... (Ctrl+D to finish)")
        code = sys.stdin.read()

    if not code.strip():
        print("Error: No code provided")
        return 1

    team = CodeReviewTeam()
    result = await team.review(code)
    print(team.format_report(result))
    return 0 if result["verdict"] != "REJECT" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
