"""Data Pipeline Monitor — 2-agent monitoring + alerting system.

Agents:
- Monitor: Analyzes pipeline metrics, detects anomalies
- Alerter: Generates actionable alerts with severity and remediation steps

Usage:
    python main.py --pipeline "ETL weather-ingest" --metrics '{"lag": 45, "errors": 3, "rows": 12000}'
    python main.py --metrics-file pipeline-metrics.json
"""

import argparse
import asyncio
import json
import os
import sys

from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator
from src.sdk.llm_agent import LLMAgent

MONITOR_PROMPT = """You are a data pipeline reliability engineer. Given pipeline metrics:
1. Identify anomalies (spikes, drops, trends out of normal range)
2. Calculate health score (0-100) based on: lag, error rate, throughput, data quality
3. Compare against typical baselines (flag anything >2 sigma from normal)
4. Classify pipeline state: HEALTHY / DEGRADED / FAILING / DOWN
Output JSON: {"health_score": int, "state": "...", "anomalies": [...], "diagnosis": "..."}"""

ALERTER_PROMPT = """You are an on-call SRE generating actionable alerts from pipeline diagnostics.
Given a monitor's analysis:
1. Assign severity: P0 (immediate action) / P1 (next hour) / P2 (today) / P3 (this week)
2. Write an alert message suitable for Slack/PagerDuty (clear, concise, actionable)
3. Provide 2-3 concrete remediation steps in order
4. Estimate impact (data loss risk, downstream effects, SLA impact)
5. Suggest if this needs a runbook update
Output in Markdown with emoji severity indicators."""


async def main():
    parser = argparse.ArgumentParser(description="AI Data Pipeline Monitor (2-agent team)")
    parser.add_argument("--pipeline", default="unnamed", help="Pipeline name")
    parser.add_argument("--metrics", default="{}", help="JSON metrics string")
    parser.add_argument("--metrics-file", help="Path to JSON metrics file")
    parser.add_argument("--api-key", default="", help="DeepSeek API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: Set DEEPSEEK_API_KEY or pass --api-key")
        return 1

    if args.metrics_file:
        with open(args.metrics_file, encoding="utf-8") as f:
            metrics = json.load(f)
    else:
        metrics = json.loads(args.metrics)

    monitor = LLMAgent("monitor", "Pipeline Monitor", MONITOR_PROMPT, api_key=api_key)
    alerter = LLMAgent("alerter", "Alert Generator", ALERTER_PROMPT, api_key=api_key)

    agents = {"monitor": monitor, "alerter": alerter}
    strategy = ManagerWorkerStrategy(
        manager_agent_id="alerter",
        worker_agent_ids=["monitor"],
    )

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id="pipeline-monitor",
        agents=agents,
        strategy=strategy,
        initial_task={
            "prompt": (
                f"Pipeline: {args.pipeline}\n"
                f"Metrics: {json.dumps(metrics, indent=2)}\n\n"
                "Monitor: analyze these metrics for anomalies.\n"
                "Alerter: generate appropriate alerts based on the analysis."
            ),
        },
    )

    if result["status"] != "completed":
        print(f"Error: Team failed — {result.get('error', 'unknown')}")
        return 1

    print(f"# Pipeline Health Report: {args.pipeline}")
    print(result.get("synthesis", json.dumps(result.get("worker_results", {}), indent=2)))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
