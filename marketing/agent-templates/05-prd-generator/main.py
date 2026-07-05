"""PRD Generator — 3-agent multi-perspective product spec.

Agents:
- PM (Product Manager): Defines user stories, scope, success metrics
- Engineer: Assesses technical feasibility, architecture, effort
- Designer: Evaluates UX, accessibility, visual consistency

Usage:
    python main.py --idea "A CLI tool that auto-generates API documentation"
    python main.py --idea "Mobile app for tracking plant watering" --output prd.md
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import GroupChatStrategy, MultiAgentOrchestrator
from src.sdk.llm_agent import LLMAgent

PM_PROMPT = """You are a senior Product Manager. Given a product idea:
1. Define the target user persona
2. Write 3-5 core user stories (As a... I want... So that...)
3. Define MVP scope vs. v2 features
4. Propose 3 success metrics (quantifiable)
5. Identify key risks and assumptions
Be specific, not generic. Output in structured Markdown."""

ENGINEER_PROMPT = """You are a senior engineer evaluating a product idea for technical feasibility.
1. Propose a high-level architecture (stack, services, data model)
2. Identify the hardest technical challenge
3. Estimate effort: S (<1 week), M (1-3 weeks), L (1-3 months), XL (3+ months)
4. Flag any third-party dependencies or API limitations
5. Suggest an MVP tech stack with justification
Be concrete — name specific technologies, not generic categories."""

DESIGNER_PROMPT = """You are a UX designer evaluating a product idea.
1. Describe the core user flow (entry → goal, 3-5 steps)
2. Identify accessibility requirements (WCAG level, input methods)
3. Propose 2-3 key screen layouts (describe, don't draw)
4. Flag any UX risks (confusing workflows, information overload)
5. Suggest visual direction (style, tone, reference products)
Output in structured Markdown."""


async def main():
    parser = argparse.ArgumentParser(description="AI PRD Generator (3-agent team)")
    parser.add_argument("--idea", required=True, help="Product idea to spec out")
    parser.add_argument("--output", default="", help="Save PRD to file")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    pm = LLMAgent("pm", "Product Manager", PM_PROMPT, api_key=api_key)
    engineer = LLMAgent("engineer", "Engineer", ENGINEER_PROMPT, api_key=api_key)
    designer = LLMAgent("designer", "Designer", DESIGNER_PROMPT, api_key=api_key)

    agents = {"pm": pm, "engineer": engineer, "designer": designer}
    strategy = GroupChatStrategy(max_rounds=4)

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="prd-gen",
        agents=agents,
        strategy=strategy,
        initial_task={
            "prompt": f"Product idea: {args.idea}\n\n"
                      "Each of you, analyze this idea from your perspective. "
                      "Be thorough and specific. Use structured Markdown."
        },
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    history = result.get("history", [])
    report = ["# PRD: " + args.idea, ""]
    for entry in history:
        report.append(f"## {entry['name']}")
        report.append(entry["content"])
        report.append("")

    full_report = "\n".join(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(full_report)
        print(f"PRD saved to {args.output}")
    else:
        print(full_report)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
