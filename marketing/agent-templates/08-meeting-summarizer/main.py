"""Meeting Summarizer — 2-agent transcript-to-action-items pipeline.

Agents:
- Transcriber (Processor): Extracts key points, decisions, and topics from raw transcript
- Summarizer: Produces a polished meeting summary with action items and owners

Usage:
    python main.py --transcript meeting-notes.txt
    python main.py --text "Alice: Let's discuss the Q3 roadmap. Bob: I think we should..."
"""

import argparse
import asyncio
import os
import sys

from src.orchestrator.multi_agent import MultiAgentOrchestrator, RoundRobinStrategy
from src.sdk.llm_agent import LLMAgent

PROCESSOR_PROMPT = """You are a meeting transcriber and note organizer. Given a raw meeting transcript:
1. Identify all participants mentioned
2. Extract key discussion topics with timestamps if present
3. Flag every decision made (with who made it)
4. Note any disagreements or unresolved points
5. List all mentioned dates, deadlines, or milestones
Output structured JSON with sections: participants, topics, decisions, disagreements, deadlines."""

SUMMARIZER_PROMPT = """You are an executive assistant producing polished meeting summaries.
Given extracted meeting notes:
1. Write a 2-3 sentence executive summary
2. Create a "Decisions Made" section (bulleted, with owners)
3. Create an "Action Items" table: | Task | Owner | Deadline | Priority |
4. Note "Discussion Highlights" — key debates and their outcomes
5. List "Next Steps" for the next meeting
Output in clean, professional Markdown suitable for sharing with stakeholders."""


async def main():
    parser = argparse.ArgumentParser(description="AI Meeting Summarizer (2-agent team)")
    parser.add_argument("--transcript", help="Path to meeting transcript file")
    parser.add_argument("--text", help="Raw meeting text")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    if args.transcript:
        with open(args.transcript, encoding="utf-8") as f:
            transcript = f.read()
    elif args.text:
        transcript = args.text
    else:
        print("Reading from stdin...")
        transcript = sys.stdin.read()

    if not transcript.strip():
        print("Error: No transcript provided")
        return 1

    processor = LLMAgent("processor", "Note Processor", PROCESSOR_PROMPT, api_key=api_key)
    summarizer = LLMAgent("summarizer", "Summarizer", SUMMARIZER_PROMPT, api_key=api_key)

    agents = {"processor": processor, "summarizer": summarizer}
    strategy = RoundRobinStrategy(agent_order=["processor", "summarizer"], max_rounds=1)

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="meeting-summary",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": f"Process and summarize this meeting:\n\n{transcript[:12000]}"},
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    bb = result.get("blackboard", {})
    print("# Meeting Summary\n")
    print(bb.get("summarizer", bb.get("processor", "No output")))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
