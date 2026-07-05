"""Multi-agent orchestration demo — Planning + ManagerWorker execution."""
import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not set in .env")
    sys.exit(1)

BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


async def demo_planning():
    """Demo 1: PlanningEngine decomposes a goal into structured execution plan."""
    from src.orchestrator.planning import PlanningEngine

    print("=" * 72)
    print("  DEMO 1 — Planning Engine: Goal → Execution Plan")
    print("=" * 72)

    goal = (
        "Analyze the code in src/orchestrator/memory.py for three aspects: "
        "1) thread safety and concurrency bugs, "
        "2) memory leak risks and TTL cleanup efficiency, "
        "3) API design improvements for the SharedBlackboard class. "
        "Produce a consolidated report."
    )

    agents = [
        {"name": "concurrency_expert", "description": "Finds race conditions, deadlocks, and thread safety issues"},
        {"name": "memory_expert", "description": "Identifies memory leaks, inefficient cleanup, TTL design issues"},
        {"name": "api_designer", "description": "Reviews API ergonomics, naming, and Pythonic design patterns"},
        {"name": "report_writer", "description": "Synthesizes findings into a structured final report"},
    ]

    print(f"\n  Goal: {goal[:90]}...")
    print(f"  Available agents: {[a['name'] for a in agents]}")
    print("\n  --- Planning (calling DeepSeek) ---\n")

    engine = PlanningEngine(api_key=API_KEY, base_url=BASE_URL, model=MODEL)
    t0 = time.time()
    plan = await engine.plan(goal, agents)
    elapsed = time.time() - t0

    print(f"  Plan generated in {elapsed:.1f}s\n")
    print(f"  Steps ({len(plan.steps)}):")
    for step in plan.steps:
        deps = f" (depends on: {step.dependencies})" if step.dependencies else ""
        pg = f" [parallel group {step.parallel_group}]" if step.parallel_group else ""
        print(f"    {step.step_id}: {step.description}")
        print(f"      → assigned: {step.assigned_agent}{deps}{pg}")
    if plan.synthesis_step:
        print(f"    {plan.synthesis_step.step_id}: {plan.synthesis_step.description}")
        print(f"      → assigned: {plan.synthesis_step.assigned_agent} (synthesis)")

    print(f"\n  Parallel groups: {plan.get_parallel_groups()}")
    print(f"  Execution order: {[s.step_id for s in plan.get_step_order()]}")
    return plan


async def demo_team_execution():
    """Demo 2: ManagerWorkerStrategy — manager decomposes, workers parallel, manager synthesizes."""
    from src.orchestrator.memory import SharedBlackboard
    from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator
    from src.sdk.llm_agent import LLMAgent

    print("\n\n" + "=" * 72)
    print("  DEMO 2 — Manager/Worker Team: Parallel Code Review")
    print("=" * 72)

    task_code = '''
def put(self, key: str, value: Any, created_by: str, ttl: Optional[float] = None) -> None:
    """Store a value on the blackboard."""
    entry = BlackboardEntry(key=key, value=value, created_by=created_by)
    self._store[key] = entry
    if ttl is not None:
        self._ttl[key] = time.time() + ttl
    event = self._watchers.pop(key, None)
    if event is not None:
        event.set()

def compare_and_swap(self, key: str, expected_version: int, new_value: Any, created_by: str) -> bool:
    """Atomically update if version matches. Returns True on success."""
    entry = self._store.get(key)
    if entry is None or entry.version != expected_version:
        return False
    entry.value = new_value
    entry.version += 1
    entry.created_by = created_by
    return True
'''

    # Three specialized workers + one manager
    manager = LLMAgent(
        "manager", "Manager",
        system_prompt="""You are a technical lead managing a code review team.
Given a task and code, decompose it into subtasks for your specialists.
Output JSON: {"subtasks": [{"worker": "<worker_id>", "task": "<specific task for that worker>"}]}

Available workers:
- security: Finds security vulnerabilities (SQLi, XSS, hardcoded secrets, unsafe patterns)
- quality: Finds bugs, logic errors, race conditions, missing error handling
- performance: Finds memory leaks, inefficient code, missing optimizations""",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )

    security = LLMAgent(
        "security", "Security Reviewer",
        system_prompt="""You are a senior security engineer. Review the code for vulnerabilities.
Focus on: race conditions, unsafe concurrent access, missing input validation, insecure defaults.
Output a JSON report: {"findings": [...], "risk_level": "critical|high|medium|low"}""",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )

    quality = LLMAgent(
        "quality", "Quality Reviewer",
        system_prompt="""You are a senior software engineer. Review the code for bugs and quality issues.
Focus on: logic errors, edge cases, error handling gaps, mutation issues, API design.
Output a JSON report: {"findings": [...], "quality_score": "A+|A|B|C|D|F"}""",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )

    performance = LLMAgent(
        "performance", "Performance Reviewer",
        system_prompt="""You are a performance engineer. Review the code for efficiency.
Focus on: unnecessary allocations, blocking operations, TTL cleanup efficiency, data structure choices.
Output a JSON report: {"findings": [...], "perf_score": "A+|A|B|C|D|F"}""",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )

    agents = {
        "manager": manager,
        "security": security,
        "quality": quality,
        "performance": performance,
    }

    strategy = ManagerWorkerStrategy(
        manager_agent_id="manager",
        worker_agent_ids=["security", "quality", "performance"],
    )
    orchestrator = MultiAgentOrchestrator()
    bb = SharedBlackboard("demo-team")

    print("\n  --- Executing Manager/Worker team (3 workers in parallel) ---\n")

    t0 = time.time()
    result = await orchestrator.run_team(
        team_id="demo-team",
        agents=agents,
        strategy=strategy,
        initial_task={
            "prompt": f"Review this Python code for security, quality, and performance issues:\n```python\n{task_code}\n```\n\nDecompose review tasks to your 3 specialists, then synthesize their findings.",
        },
        blackboard=bb,
    )
    elapsed = time.time() - t0

    print(f"\n  Team execution completed in {elapsed:.1f}s")
    print(f"  Status: {result['status']}")
    print(f"  Manager: {result.get('manager', 'N/A')}")
    print(f"  Workers completed: {len(result.get('worker_results', {}))}")
    print(f"  Duration: {result.get('duration', 0):.1f}s")

    print("\n  --- Worker Results (blackboard) ---")
    for key in sorted(bb.snapshot().keys()):
        val = bb.get(key)
        if isinstance(val, str) and len(val) > 200:
            val = val[:200] + "..."
        print(f"    [{key}] {val}")

    print("\n  --- Synthesis ---")
    synthesis = result.get("synthesis", "")
    if isinstance(synthesis, str) and len(synthesis) > 600:
        synthesis = synthesis[:600] + "..."
    print(f"    {synthesis}")

    return result


async def demo_round_robin():
    """Demo 3: RoundRobin — two agents iteratively improve a solution."""
    from src.orchestrator.memory import SharedBlackboard
    from src.orchestrator.multi_agent import MultiAgentOrchestrator, RoundRobinStrategy
    from src.sdk.llm_agent import LLMAgent

    print("\n\n" + "=" * 72)
    print("  DEMO 3 — Round Robin: Two-agent iterative refinement")
    print("=" * 72)

    coder = LLMAgent(
        "coder", "Coder",
        system_prompt="Write clean Python code. Be concise. Output only the code, no explanation.",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )
    reviewer = LLMAgent(
        "reviewer", "Reviewer",
        system_prompt="Review the provided code and suggest exactly ONE improvement. Be specific and concise. Output the improved code.",
        api_key=API_KEY, base_url=BASE_URL, model=MODEL,
    )

    agents = {"coder": coder, "reviewer": reviewer}
    strategy = RoundRobinStrategy(agent_order=["coder", "reviewer"], max_rounds=1)
    orchestrator = MultiAgentOrchestrator()

    print("\n  --- Round-robin: coder → reviewer (1 round) ---\n")

    t0 = time.time()
    result = await orchestrator.run_team(
        team_id="rr-demo",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": "Write a Python function to find the top-N most frequent words in a text file efficiently."},
    )
    elapsed = time.time() - t0

    print(f"  Completed in {elapsed:.1f}s")
    print(f"  Status: {result['status']}")
    print(f"  History entries: {len(result.get('history', []))}")

    bb = result.get("blackboard", {})
    if isinstance(bb, dict):
        for key, val in bb.items():
            if isinstance(val, str):
                print(f"\n  [{key}]:\n    {val[:400]}")
    else:
        for key in sorted(bb.snapshot().keys()):
            val = bb.get(key)
            if isinstance(val, str):
                print(f"\n  [{key}]:\n    {val[:400]}")

    return result


async def main():
    print("\n" + "█" * 72)
    print("  MULTI-AGENT ORCHESTRATION SYSTEM — LIVE DEMO")
    print("  DeepSeek API  |  ManagerWorker  |  RoundRobin  |  PlanningEngine")
    print("█" * 72)

    try:
        await demo_planning()
    except Exception as e:
        print(f"\n  [Planning demo error: {e}]")

    try:
        await demo_team_execution()
    except Exception as e:
        print(f"\n  [ManagerWorker demo error: {e}]")

    try:
        await demo_round_robin()
    except Exception as e:
        print(f"\n  [RoundRobin demo error: {e}]")

    print("\n\n" + "█" * 72)
    print("  ALL DEMOS COMPLETE")
    print("█" * 72)


if __name__ == "__main__":
    asyncio.run(main())
