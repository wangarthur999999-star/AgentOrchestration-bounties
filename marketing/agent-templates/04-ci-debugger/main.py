"""CI Debugger — 2-agent log analysis + fix suggestion pipeline.

Agents:
- Log Analyzer: Parses CI failure logs, identifies root cause
- Fix Suggester: Proposes concrete code fixes based on analysis

Usage:
    python main.py --log ci-failure.log
    python main.py --log-url https://github.com/user/repo/actions/runs/123
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import MultiAgentOrchestrator, RoundRobinStrategy
from src.sdk.llm_agent import LLMAgent

LOG_ANALYZER_PROMPT = """You are a CI/CD engineer debugging failed pipelines. Given CI logs:
1. Identify the exact error (not symptoms — the root cause)
2. Locate the file and line number if present
3. Classify: test failure / build error / dependency issue / flaky test / infra timeout
4. Rate severity: BLOCKER / HIGH / MEDIUM / LOW
Output structured JSON: {"error_type":"...", "location":"...", "root_cause":"...", "severity":"..."}"""

FIX_SUGGESTER_PROMPT = """You are a senior developer proposing fixes for CI failures.
Given an error analysis, propose a concrete fix:
1. Show the code change (diff-style if possible)
2. Explain why this fix addresses the root cause
3. Flag any risks or side effects
4. Suggest a verification step (e.g., "run test X locally")
Output in Markdown with clear sections."""


async def main():
    parser = argparse.ArgumentParser(description="AI CI Debugger (2-agent team)")
    parser.add_argument("--log", help="Path to CI log file")
    parser.add_argument("--log-url", help="URL to CI log (GitHub Actions, etc.)")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    if args.log:
        with open(args.log, encoding="utf-8") as f:
            log_content = f.read()
    elif args.log_url:
        print(f"Fetching {args.log_url} ... (implement with httpx for production)")
        log_content = f"Log from: {args.log_url}\n[Log content would be fetched here]"
    else:
        print("Reading from stdin...")
        log_content = sys.stdin.read()

    if not log_content.strip():
        print("Error: No log content provided")
        return 1

    analyzer = LLMAgent("analyzer", "Log Analyzer", LOG_ANALYZER_PROMPT, api_key=api_key)
    fixer = LLMAgent("fixer", "Fix Suggester", FIX_SUGGESTER_PROMPT, api_key=api_key)

    agents = {"analyzer": analyzer, "fixer": fixer}
    strategy = RoundRobinStrategy(agent_order=["analyzer", "fixer"], max_rounds=1)

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="ci-debug",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": f"Debug this CI failure:\n\n```\n{log_content[:12000]}\n```"},
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    bb = result.get("blackboard", {})
    print("=== CI DEBUG REPORT ===\n")
    print("--- Analysis ---")
    print(bb.get("analyzer", "No analysis"))
    print("\n--- Suggested Fix ---")
    print(bb.get("fixer", "No fix suggested"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
