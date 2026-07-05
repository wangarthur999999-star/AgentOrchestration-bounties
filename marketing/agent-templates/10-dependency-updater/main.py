"""Dependency Updater — 2-agent scan + upgrade safety pipeline.

Agents:
- Scanner: Checks project dependencies for outdated packages and security advisories
- Upgrader: Proposes safe upgrade paths with changelog analysis and risk assessment

Usage:
    python main.py --requirements requirements.txt
    python main.py --pyproject pyproject.toml
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import MultiAgentOrchestrator, RoundRobinStrategy
from src.sdk.llm_agent import LLMAgent

SCANNER_PROMPT = """You are a dependency security auditor. Given a project's dependency list:
1. Identify packages that are out of date (compare against latest known versions)
2. Flag packages with known security vulnerabilities (CVE if known)
3. Categorize each: MAJOR_UPDATE / MINOR_UPDATE / PATCH / CURRENT / UNMAINTAINED
4. Identify transitive dependency risks (packages that pull in vulnerable sub-dependencies)
5. Note any end-of-life or deprecated packages
Output structured JSON: [{"package":"...", "current":"...", "latest":"...", "category":"...", "risk":"LOW|MEDIUM|HIGH|CRITICAL", "cves":[...]}]"""

UPGRADER_PROMPT = """You are a maintainer planning dependency upgrades safely.
Given a dependency scan:
1. Propose upgrade order (which to do first, which can batch)
2. For each upgrade: breaking changes to expect (from changelog/migration guides), test areas to focus on
3. Risk assessment: SAFE (patch only) / CAUTIOUS (minor, check tests) / DANGEROUS (major, read migration guide)
4. Suggest a rollback plan for each risky upgrade
5. Generate the updated requirements.txt or pyproject.toml entries
Output in Markdown with clear upgrade instructions and copy-paste-ready dependency lines."""


async def main():
    parser = argparse.ArgumentParser(description="AI Dependency Updater (2-agent team)")
    parser.add_argument("--requirements", help="Path to requirements.txt")
    parser.add_argument("--pyproject", help="Path to pyproject.toml")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    deps = ""
    if args.requirements:
        with open(args.requirements, encoding="utf-8") as f:
            deps = f.read()
    elif args.pyproject:
        with open(args.pyproject, encoding="utf-8") as f:
            deps = f.read()
    else:
        print("Reading from stdin...")
        deps = sys.stdin.read()

    if not deps.strip():
        print("Error: No dependency file provided")
        return 1

    scanner = LLMAgent("scanner", "Dependency Scanner", SCANNER_PROMPT, api_key=api_key)
    upgrader = LLMAgent("upgrader", "Upgrade Planner", UPGRADER_PROMPT, api_key=api_key)

    agents = {"scanner": scanner, "upgrader": upgrader}
    strategy = RoundRobinStrategy(agent_order=["scanner", "upgrader"], max_rounds=1)

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="dep-update",
        agents=agents,
        strategy=strategy,
        initial_task={
            "prompt": (
                f"Analyze these dependencies for outdated packages and security issues:\n\n"
                f"```\n{deps[:8000]}\n```\n\n"
                "Scanner: audit these dependencies.\n"
                "Upgrader: propose safe upgrade paths."
            ),
        },
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    bb = result.get("blackboard", {})
    print("# Dependency Update Report\n")
    print("## Scan Results")
    print(bb.get("scanner", "No scan"))
    print("\n## Upgrade Plan")
    print(bb.get("upgrader", "No upgrade plan"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
