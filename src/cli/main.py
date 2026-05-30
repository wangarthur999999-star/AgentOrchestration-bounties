"""CLI entry point for multi-agent orchestration."""

import argparse
import asyncio
import json
import os
import sys

from src.common.config import Config
from src.common.logging import configure_logging
from src.orchestrator.multi_agent import (
    DebateStrategy,
    GroupChatStrategy,
    HybridStrategy,
    ManagerWorkerStrategy,
    MultiAgentOrchestrator,
    RoundRobinStrategy,
)
from src.sdk.llm_agent import LLMAgent
from src.sdk.tools import ToolRegistry

AGENT_TEMPLATES = {
    "analyst": "You are a data analyst. Break down problems methodically. Provide clear, data-driven insights.",
    "engineer": "You are a software engineer. Write clean, working code. Consider edge cases and error handling.",
    "critic": "You are a constructive critic. Find flaws in reasoning and propose improvements.",
    "researcher": "You are a researcher. Gather and synthesize information from multiple perspectives.",
    "planner": "You are a strategic planner. Decompose goals into actionable steps with dependencies.",
}

STRATEGIES = {
    "round-robin": RoundRobinStrategy,
    "group-chat": GroupChatStrategy,
    "debate": DebateStrategy,
    "manager-worker": ManagerWorkerStrategy,
}


def _get_api_config(args) -> tuple[str, str, str]:
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = args.base_url or os.environ.get("AO_BASE_URL", "https://api.deepseek.com/v1")
    model = args.model or os.environ.get("AO_MODEL", "deepseek-chat")
    return api_key, base_url, model


def _build_agent(agent_id: str, template: str, api_key: str, base_url: str, model: str) -> LLMAgent:
    system_prompt = AGENT_TEMPLATES.get(template, template)
    return LLMAgent(
        agent_id=agent_id,
        name=f"{template}-{agent_id}",
        system_prompt=system_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def _parse_agents_arg(agents_arg: str, api_key: str, base_url: str, model: str) -> dict[str, LLMAgent]:
    agents = {}
    for pair in agents_arg.split(","):
        pair = pair.strip()
        if ":" in pair:
            agent_id, template = pair.split(":", 1)
        else:
            agent_id = template = pair
        agents[agent_id] = _build_agent(agent_id, template, api_key, base_url, model)
    return agents


def cmd_team_run(args) -> None:
    """Run a multi-agent team with a conversation strategy."""
    api_key, base_url, model = _get_api_config(args)

    if not api_key:
        print("Error: API key required. Set DEEPSEEK_API_KEY or use --api-key.")
        sys.exit(1)

    agents = _parse_agents_arg(args.agents, api_key, base_url, model)

    strategy_cls = STRATEGIES.get(args.strategy)
    if strategy_cls is None:
        print(f"Unknown strategy: {args.strategy}. Available: {', '.join(STRATEGIES)}")
        sys.exit(1)

    if args.strategy == "debate":
        strategy = DebateStrategy(debate_topic=args.prompt, max_rounds=args.rounds)
    elif args.strategy == "manager-worker":
        agent_ids = list(agents.keys())
        strategy = ManagerWorkerStrategy(
            manager_agent_id=agent_ids[0],
            worker_agent_ids=agent_ids[1:] if len(agent_ids) > 1 else agent_ids,
            max_rounds=args.rounds,
        )
    elif args.strategy == "round-robin":
        strategy = RoundRobinStrategy(agent_order=list(agents.keys()), max_rounds=args.rounds)
    else:
        strategy = strategy_cls(max_rounds=args.rounds)

    orchestrator = MultiAgentOrchestrator()
    result = asyncio.run(orchestrator.run_team(
        team_id=args.team_id or "cli-team",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": args.prompt},
    ))

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def cmd_plan(args) -> None:
    """Decompose a goal into an execution plan using the PlanningEngine."""
    api_key, base_url, model = _get_api_config(args)

    if not api_key:
        print("Error: API key required. Set DEEPSEEK_API_KEY or use --api-key.")
        sys.exit(1)

    from src.orchestrator.planning import PlanningEngine

    available_agents = [{"name": name} for name in AGENT_TEMPLATES]
    engine = PlanningEngine(api_key=api_key, base_url=base_url, model=model)

    async def run_plan():
        plan = await engine.plan(args.goal, available_agents, max_steps=args.max_steps)
        return plan

    plan = asyncio.run(run_plan())
    print(engine.plan_summary(plan))


def cmd_list_agents(args) -> None:  # noqa: ARG001
    """List available agent templates."""
    print("Available agent templates:")
    for name, prompt in AGENT_TEMPLATES.items():
        print(f"  {name}: {prompt[:80]}...")
    print()
    print("Available strategies:")
    for name in STRATEGIES:
        print(f"  {name}")


def cmd_list_tools(args) -> None:  # noqa: ARG001
    """List available built-in tools."""
    print("Built-in tools:")
    print("  search: Web search via configurable backend")
    print("  read_file: Read a file from the filesystem")
    print("  run_code: Execute Python code in a sandbox")
    print()
    print("Use `multi-agent run --tools search,read_file` to enable tools.")


def cli():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Orchestration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  multi-agent team run --agents "manager:planner,worker1:engineer" --strategy manager-worker --prompt "Build a REST API"
  multi-agent team run --agents "pro:analyst,con:critic" --strategy debate --prompt "Should we use microservices?"
  multi-agent plan --goal "Add real-time notifications to the dashboard"
  multi-agent list agents
        """,
    )
    parser.add_argument("--api-key", help="LLM API key (or set DEEPSEEK_API_KEY)")
    parser.add_argument("--base-url", help="LLM API base URL")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # team run
    team_parser = subparsers.add_parser("team", help="Manage agent teams")
    team_subs = team_parser.add_subparsers(dest="team_command")
    run_parser = team_subs.add_parser("run", help="Run a multi-agent team")
    run_parser.add_argument("--agents", "-a", required=True, help="Agent pairs: 'id:template,id:template,...'")
    run_parser.add_argument("--strategy", "-s", required=True, choices=list(STRATEGIES), help="Conversation strategy")
    run_parser.add_argument("--prompt", "-p", required=True, help="Task prompt")
    run_parser.add_argument("--rounds", "-r", type=int, default=5, help="Max rounds (default: 5)")
    run_parser.add_argument("--team-id", help="Team identifier")
    run_parser.add_argument("--tools", help="Comma-separated tool names to enable")

    # plan
    plan_parser = subparsers.add_parser("plan", help="Decompose a goal into steps")
    plan_parser.add_argument("--goal", "-g", required=True, help="Goal to decompose")
    plan_parser.add_argument("--max-steps", "-n", type=int, default=8, help="Max plan steps")

    # list
    list_parser = subparsers.add_parser("list", help="List resources")
    list_subs = list_parser.add_subparsers(dest="list_command")
    list_agents = list_subs.add_parser("agents", help="List agent templates")
    list_agents.set_defaults(func=cmd_list_agents)
    list_tools = list_subs.add_parser("tools", help="List built-in tools")
    list_tools.set_defaults(func=cmd_list_tools)

    args = parser.parse_args()

    if args.verbose:
        configure_logging("DEBUG")
    else:
        configure_logging("WARNING")

    if args.command == "team" and hasattr(args, "team_command") and args.team_command == "run":
        cmd_team_run(args)
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "list":
        if hasattr(args, "func"):
            args.func(args)
        elif hasattr(args, "list_command") and args.list_command == "agents":
            cmd_list_agents(args)
        elif hasattr(args, "list_command") and args.list_command == "tools":
            cmd_list_tools(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
