"""AI-powered bounty solver — generates solutions for eligible bounties."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from src.bounty_hunter.scanner import Bounty

logger = logging.getLogger(__name__)

SOLVER_SYSTEM_PROMPT = """You are an expert software developer solving open source bounties.
Given a bounty description, analyze it and produce:

1. Feasibility assessment: can you solve this with confidence?
2. Implementation plan: step-by-step approach
3. If feasible, the actual code solution

Output ONLY valid JSON:
{
  "feasible": true/false,
  "confidence": 0-100,
  "estimated_hours": 0.5-40,
  "reasoning": "Why this is/isn't feasible",
  "plan": ["step 1", "step 2"],
  "solution": {
    "files": [
      {
        "path": "relative/path/to/file.py",
        "content": "full file content",
        "description": "What this file does"
      }
    ],
    "test_files": [
      {
        "path": "tests/test_file.py",
        "content": "test content"
      }
    ],
    "instructions": "How to apply the solution"
  }
}

Be realistic about feasibility. If the bounty requires access to a private codebase,
detailed domain knowledge, or the description is too vague, mark as infeasible.
"""


@dataclass
class Solution:
    feasible: bool
    confidence: int
    estimated_hours: float
    reasoning: str
    plan: list[str] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    test_files: list[dict] = field(default_factory=list)
    instructions: str = ""


class BountySolver:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1"):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def evaluate(self, bounty: Bounty) -> Solution:
        """Evaluate whether a bounty is solvable and generate solution if so."""
        prompt = self._build_prompt(bounty)

        try:
            response = await self._client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SOLVER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=8192,
                temperature=0.3,
            )

            raw = response.choices[0].message.content or "{}"
            return self._parse_solution(raw)

        except Exception as e:
            logger.error(f"Solver error for {bounty.id}: {e}")
            return Solution(
                feasible=False,
                confidence=0,
                estimated_hours=0,
                reasoning=f"Error: {e}",
            )

    async def evaluate_batch(self, bounties: list[Bounty]) -> list[tuple[Bounty, Solution]]:
        """Evaluate multiple bounties in parallel."""
        tasks = [self.evaluate(b) for b in bounties]
        solutions = await __import__("asyncio").gather(*tasks, return_exceptions=True)

        results = []
        for bounty, solution in zip(bounties, solutions):
            if isinstance(solution, Exception):
                results.append((bounty, Solution(False, 0, 0, f"Error: {solution}")))
            else:
                results.append((bounty, solution))
        return results

    def _build_prompt(self, bounty: Bounty) -> str:
        return f"""Bounty Title: {bounty.title}
Platform: {bounty.platform}
Amount: ${bounty.amount_usd:.2f} {bounty.currency}
Difficulty: {bounty.difficulty}
Tags: {', '.join(bounty.tags)}
Competition: {bounty.submissions_count} existing submissions

Description:
{bounty.description[:3000]}

Repo: {bounty.repo_url}

Assess whether this bounty can be solved. Be realistic.
If feasible, provide a complete solution with code.
"""

    def _parse_solution(self, raw: str) -> Solution:
        import json

        try:
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1])

            data = json.loads(raw)
            return Solution(
                feasible=data.get("feasible", False),
                confidence=data.get("confidence", 0),
                estimated_hours=data.get("estimated_hours", 0),
                reasoning=data.get("reasoning", ""),
                plan=data.get("plan", []),
                files=data.get("solution", {}).get("files", []),
                test_files=data.get("solution", {}).get("test_files", []),
                instructions=data.get("solution", {}).get("instructions", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse solution: {e}")
            return Solution(False, 0, 0, f"Parse error: {raw[:200]}")
