"""Research Synthesizer — 2-agent deep research + synthesis pipeline.

Agents:
- Researcher: Deep-dives into a topic, gathers facts, cites sources
- Synthesizer: Merges findings into a coherent, structured report

Usage:
    python main.py --topic "Latest advances in quantum computing"
    python main.py --topic "Rust vs Go performance" --format markdown
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator
from src.orchestrator.memory import SharedBlackboard
from src.sdk.llm_agent import LLMAgent

RESEARCHER_PROMPT = """You are an expert researcher. Given a topic, conduct a thorough investigation.
Cover: key concepts, recent developments, major players, competing approaches, and open questions.
Be factual. Cite specific technologies, papers, or companies when relevant.
Output a structured research brief in Markdown format with clear sections."""

SYNTHESIZER_PROMPT = """You are a senior analyst who synthesizes research into actionable reports.
Given raw research findings, produce a polished, comprehensive report with:
- Executive summary (2-3 sentences)
- Key findings (bullet points)
- Detailed analysis (organized by theme)
- Recommendations or conclusions
- Further reading suggestions
Output in well-formatted Markdown."""


async def main():
    parser = argparse.ArgumentParser(description="AI Research Synthesizer (2-agent team)")
    parser.add_argument("--topic", required=True, help="Research topic")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"], help="Output format")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    researcher = LLMAgent("researcher", "Researcher", RESEARCHER_PROMPT, api_key=api_key)
    synthesizer = LLMAgent("synthesizer", "Synthesizer", SYNTHESIZER_PROMPT, api_key=api_key)

    agents = {"researcher": researcher, "synthesizer": synthesizer}
    strategy = ManagerWorkerStrategy(
        manager_agent_id="synthesizer",
        worker_agent_ids=["researcher"],
    )

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="research-synth",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": f"Research topic: {args.topic}"},
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    if args.format == "json":
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result.get("synthesis", result.get("worker_results", {}).get("researcher", "No output")))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
