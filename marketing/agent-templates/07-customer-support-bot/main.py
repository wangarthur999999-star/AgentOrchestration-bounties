"""Customer Support Bot — 3-agent triage + solve + escalate pipeline.

Agents:
- Triage: Classifies the issue, determines priority and category
- Solver: Provides step-by-step resolution for known issues
- Escalator: Handles complex cases that need human intervention

Usage:
    python main.py --issue "I can't log in after the latest update"
    python main.py --issue "Billing shows wrong amount" --customer-id 12345
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator
from src.sdk.llm_agent import LLMAgent

TRIAGE_PROMPT = """You are a customer support triage specialist. Given a customer issue:
1. Categorize: BILLING / AUTH / BUG / FEATURE_REQUEST / ONBOARDING / PERFORMANCE / OTHER
2. Assign priority: URGENT (service down) / HIGH (blocked) / MEDIUM (workaround exists) / LOW (cosmetic)
3. Determine if this can be solved automatically or needs human escalation
4. Extract key details: product area, affected feature, error messages mentioned
Output JSON: {"category":"...", "priority":"...", "auto_solvable": bool, "key_details":"...", "sentiment":"positive|neutral|frustrated|angry"}"""

SOLVER_PROMPT = """You are a technical support engineer solving customer issues.
Given a triaged issue:
1. Provide a clear, step-by-step resolution (numbered steps)
2. Include exact commands, URLs, or settings paths the customer needs
3. Anticipate 2 common follow-up questions and answer them
4. Link to relevant docs/FAQs if applicable
5. If you can't fully resolve it, explain what's needed from engineering
Output in friendly, empathetic Markdown. Use plain language — no jargon without explanation."""

ESCALATOR_PROMPT = """You are an escalation manager handling complex support cases.
Given an issue that couldn't be auto-resolved:
1. Summarize what's been tried and why it failed
2. Identify which team should handle this (engineering, billing, security, etc.)
3. Draft an internal handoff note with all relevant context
4. Suggest SLA-appropriate response time
5. Propose a temporary workaround if one exists
Output in Markdown suitable for a Jira ticket or Slack handoff."""


async def main():
    parser = argparse.ArgumentParser(description="AI Customer Support Bot (3-agent team)")
    parser.add_argument("--issue", required=True, help="Customer issue description")
    parser.add_argument("--customer-id", default="anonymous", help="Customer identifier")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    triage = LLMAgent("triage", "Triage Specialist", TRIAGE_PROMPT, api_key=api_key)
    solver = LLMAgent("solver", "Solution Engineer", SOLVER_PROMPT, api_key=api_key)
    escalator = LLMAgent("escalator", "Escalation Manager", ESCALATOR_PROMPT, api_key=api_key)

    agents = {"triage": triage, "solver": solver, "escalator": escalator}
    strategy = ManagerWorkerStrategy(
        manager_agent_id="triage",
        worker_agent_ids=["solver", "escalator"],
    )

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="support-bot",
        agents=agents,
        strategy=strategy,
        initial_task={
            "prompt": (
                f"Customer ID: {args.customer_id}\n"
                f"Issue: {args.issue}\n\n"
                "Triage: classify this issue.\n"
                "Solver: provide resolution steps.\n"
                "Escalator: prepare handoff if needed."
            ),
        },
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    print(result.get("synthesis", "No synthesis available"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
