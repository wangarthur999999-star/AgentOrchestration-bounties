"""Showcase: 3 multi-agent demos in one run."""
import asyncio, json, os, time
from dotenv import load_dotenv; load_dotenv()

API_KEY = os.environ["DEEPSEEK_API_KEY"]

from src.sdk.llm_agent import LLMAgent
from src.orchestrator.multi_agent import (
    DebateStrategy, ManagerWorkerStrategy, RoundRobinStrategy, MultiAgentOrchestrator,
)
from src.orchestrator.memory import SharedBlackboard
from src.orchestrator.planning import PlanningEngine

SEP = "=" * 60


async def demo_1_debate():
    """3 agents debate: microservices vs monolith for a 5-person startup."""
    print(f"\n{SEP}")
    print("DEMO 1: Agent Debate — Microservices vs Monolith")
    print(SEP)

    agents = {
        "microservices": LLMAgent(
            "microservices", "Microservices Advocate",
            "You argue FOR microservices. Focus on independent deployability, "
            "team autonomy per service, polyglot tech stacks, and horizontal scaling. "
            "Be concise and persuasive. Keep under 120 words.",
            api_key=API_KEY,
        ),
        "monolith": LLMAgent(
            "monolith", "Monolith Advocate",
            "You argue FOR monoliths. Focus on fast development cycles, simple debugging, "
            "transactional consistency, lower operational burden, and shared codebase. "
            "Be concise and persuasive. Keep under 120 words.",
            api_key=API_KEY,
        ),
        "pragmatist": LLMAgent(
            "pragmatist", "Pragmatic Architect",
            "You evaluate both sides for a 5-person seed-stage startup. Consider: "
            "team size, funding constraints, time-to-market pressure, future scaling needs. "
            "Vote for one approach and explain your reasoning. Keep under 150 words.",
            api_key=API_KEY,
        ),
    }

    orch = MultiAgentOrchestrator()
    t0 = time.time()
    result = await orch.run_team(
        team_id="debate-showcase",
        agents=agents,
        strategy=DebateStrategy(
            debate_topic="Should a 5-person seed-stage startup use microservices or a monolith?",
            max_rounds=2,
        ),
        initial_task={"prompt": "Debate: microservices vs monolith for a 5-person seed-stage startup"},
        blackboard=SharedBlackboard("debate-showcase"),
    )
    elapsed = time.time() - t0

    print(f"\nDuration: {elapsed:.1f}s")
    print(f"Winner: {result.get('winner', 'unknown')}")
    print(f"\nVotes: {json.dumps(result.get('votes', {}), indent=2)}")
    print(f"\nPositions:")
    positions = result.get("positions", {})
    for agent_id, pos in positions.items():
        label = agent_id.replace("position/", "")
        print(f"  [{label}] {pos[:300]}...")
    print()


async def demo_2_code_review():
    """3 specialists review engine.py in parallel."""
    print(f"\n{SEP}")
    print("DEMO 2: Parallel Code Review — engine.py (Security + Quality + Performance)")
    print(SEP)

    code = open("src/orchestrator/engine.py", encoding="utf-8").read()

    manager = LLMAgent(
        "mgr", "Tech Lead",
        "You are a tech lead. Decompose this code review into 3 subtasks: "
        "security, quality, performance. Output JSON: "
        '{"subtasks": [{"worker": "security", "task": "..."}, '
        '{"worker": "quality", "task": "..."}, '
        '{"worker": "perf", "task": "..."}]}',
        api_key=API_KEY,
    )
    security = LLMAgent(
        "security", "Security Reviewer",
        "Find: injection vectors, hardcoded secrets, unsafe patterns. "
        "Output JSON: {\"findings\": [...], \"risk\": \"critical|high|medium|low\"}. "
        "Keep under 200 words.",
        api_key=API_KEY,
    )
    quality = LLMAgent(
        "quality", "Quality Reviewer",
        "Find: bugs, missing error handling, edge cases, race conditions. "
        "Output JSON: {\"findings\": [...], \"score\": \"A|B|C|D|F\"}. "
        "Keep under 200 words.",
        api_key=API_KEY,
    )
    perf = LLMAgent(
        "perf", "Performance Reviewer",
        "Find: bottlenecks, unnecessary allocations, blocking I/O, missing caching. "
        "Output JSON: {\"findings\": [...], \"score\": \"A|B|C|D|F\"}. "
        "Keep under 200 words.",
        api_key=API_KEY,
    )

    orch = MultiAgentOrchestrator()
    t0 = time.time()
    result = await orch.run_team(
        team_id="review-showcase",
        agents={"mgr": manager, "security": security, "quality": quality, "perf": perf},
        strategy=ManagerWorkerStrategy("mgr", ["security", "quality", "perf"]),
        initial_task={"prompt": f"Review this file (engine.py):\n```python\n{code[:6000]}\n```"},
        blackboard=SharedBlackboard("review-showcase"),
    )
    elapsed = time.time() - t0

    print(f"\nDuration: {elapsed:.1f}s")

    synthesis = result.get("synthesis", "No synthesis")
    print(f"\n=== SYNTHESIS ===")
    print(synthesis[:1500])

    print(f"\n=== WORKER OUTPUTS ===")
    for wid, output in result.get("worker_results", {}).items():
        print(f"  [{wid}] {output[:400]}...")
    print()


async def demo_3_planning():
    """LLM decomposes a complex goal into structured execution plan."""
    print(f"\n{SEP}")
    print("DEMO 3: Planning Engine — Goal → Structured Execution Plan")
    print(SEP)

    goal = (
        "Build a real-time dashboard that monitors agent execution metrics: "
        "throughput, latency, error rates, and cost per agent. Dashboard should "
        "auto-refresh every 5 seconds, support date range filtering, and export to CSV."
    )
    agents = [
        {"name": "backend_dev", "description": "builds APIs and WebSocket endpoints"},
        {"name": "frontend_dev", "description": "builds React components and charts"},
        {"name": "data_engineer", "description": "designs metrics pipeline and aggregation"},
        {"name": "qa_engineer", "description": "writes tests and validates functionality"},
    ]

    engine = PlanningEngine(api_key=API_KEY)
    t0 = time.time()
    plan = await engine.plan(goal, agents)
    elapsed = time.time() - t0

    print(f"\nDuration: {elapsed:.1f}s")
    print(f"\nGoal: {plan.goal}")
    print(f"\nSteps ({len(plan.steps)} total):")
    for s in plan.steps:
        deps = f" (depends on: {', '.join(s.dependencies)})" if s.dependencies else ""
        pg = f" [parallel group: {s.parallel_group}]" if s.parallel_group else ""
        print(f"  {s.step_id} → {s.assigned_agent}{pg}{deps}")
        print(f"      {s.description[:120]}")

    if plan.synthesis_step:
        print(f"\n  Synthesis: {plan.synthesis_step.step_id} → {plan.synthesis_step.assigned_agent}")

    order = [s.step_id for s in plan.get_step_order()]
    print(f"\nExecution order: {' → '.join(order)}")
    print()


async def main():
    print("MULTI-AGENT SYSTEM SHOWCASE")
    print(f"Backend: DeepSeek API | Model: deepseek-chat")
    print(f"3 demos ~60s each...")

    await demo_1_debate()
    await demo_2_code_review()
    await demo_3_planning()

    print(f"{SEP}")
    print("ALL 3 DEMOS COMPLETE")
    print(f"{SEP}")


if __name__ == "__main__":
    asyncio.run(main())
