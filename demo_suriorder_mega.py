"""Mega analysis: 6-agent-team deep dive on SuriOrder."""
import asyncio, json, os, sys, time
from dotenv import load_dotenv; load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = os.environ["DEEPSEEK_API_KEY"]

from src.sdk.llm_agent import LLMAgent
from src.orchestrator.multi_agent import (
    DebateStrategy, ManagerWorkerStrategy, MultiAgentOrchestrator,
)
from src.orchestrator.memory import SharedBlackboard
from src.orchestrator.planning import PlanningEngine

BASE = r"C:\Users\wanga\OneDrive\Desktop\SuriOrder"
SEP = "=" * 64


def read_code(path):
    with open(os.path.join(BASE, path), encoding="utf-8") as f:
        return f.read()


async def review_file(name: str, path: str, focus: str):
    """3-agent parallel code review."""
    code = read_code(path)
    manager = LLMAgent("mgr", "Lead",
        f"You are a tech lead. Decompose this review into 3 subtasks for security, quality, performance on {name}. "
        'Output JSON: {"subtasks": [{"worker": "security", "task": "..."}, {"worker": "quality", "task": "..."}, {"worker": "perf", "task": "..."}]}',
        api_key=API_KEY)
    security = LLMAgent("security", "Security",
        f"Review {name}. Focus on: SQL injection, XSS, auth bypass, hardcoded secrets, path traversal, injection vectors. "
        "Output JSON findings. Keep under 200 words.",
        api_key=API_KEY)
    quality = LLMAgent("quality", "Quality",
        f"Review {name}. Focus on: {focus}. Bugs, error handling gaps, race conditions, edge cases, type safety. "
        "Output JSON findings. Keep under 200 words.",
        api_key=API_KEY)
    perf = LLMAgent("perf", "Performance",
        f"Review {name}. Find: N+1 queries, missing indexes, blocking operations, memory leaks, unbounded queries. "
        "Output JSON findings. Keep under 200 words.",
        api_key=API_KEY)

    orch = MultiAgentOrchestrator()
    result = await orch.run_team(
        team_id=f"review-{name}",
        agents={"mgr": manager, "security": security, "quality": quality, "perf": perf},
        strategy=ManagerWorkerStrategy("mgr", ["security", "quality", "perf"]),
        initial_task={"prompt": f"Review this file ({name}):\n```\n{code[:6000]}\n```"},
        blackboard=SharedBlackboard(f"review-{name}"),
    )
    return result


async def debate_sqlite_vs_pg():
    """3-agent debate: SQLite vs PostgreSQL for SuriOrder."""
    agents = {
        "keep_sqlite": LLMAgent("keep_sqlite", "SQLite Advocate",
            "You argue to KEEP SQLite. SuriOrder is on Render free tier, single server, "
            "5-person team. SQLite: zero ops, no connection pooling, WAL mode concurrency is enough, "
            "backup is file copy, cloud restore is simple. PostgreSQL adds cost, latency, and operational burden. "
            "Keep under 120 words. Be sharp.",
            api_key=API_KEY),
        "migrate_pg": LLMAgent("migrate_pg", "PostgreSQL Advocate",
            "You argue to MIGRATE to PostgreSQL. As SuriOrder adds B2B catering and pickup points, "
            "SQLite WAL will bottleneck. PostgreSQL gives: concurrent writes, JSONB for menu metadata, "
            "full-text search for dish discovery, row-level security, better analytics queries. "
            "Render offers managed PostgreSQL. Keep under 120 words.",
            api_key=API_KEY),
        "architect": LLMAgent("architect", "Pragmatic Architect",
            "Evaluate both sides for SuriOrder current stage: free tier, Suriname market (small), "
            "single server, 41 tests, B2B features in early rollout. Consider migration cost vs future needs. "
            "Vote and explain. Keep under 150 words.",
            api_key=API_KEY),
    }
    orch = MultiAgentOrchestrator()
    return await orch.run_team(
        team_id="debate-db",
        agents=agents,
        strategy=DebateStrategy(debate_topic="Should SuriOrder migrate from SQLite to PostgreSQL?", max_rounds=2),
        initial_task={"prompt": "Debate: SQLite vs PostgreSQL for SuriOrder"},
        blackboard=SharedBlackboard("debate-db"),
    )


async def plan_ai_menu_feature():
    """LLM decomposes an AI menu feature into execution plan."""
    goal = (
        "Add AI-powered menu item enhancement to SuriOrder: restaurant owners upload a dish photo, "
        "LLM generates multilingual descriptions (nl/en/zh), suggests pricing based on ingredient analysis, "
        "auto-categorizes the dish, and generates an appealing 50-character short title optimized for the "
        "WhatsApp menu card. Results must be editable before saving."
    )
    agents = [
        {"name": "backend_dev", "description": "Node.js/Express API routes, SQLite schema changes"},
        {"name": "frontend_dev", "description": "Vanilla JS + HTML admin panel UI, image upload, edit form"},
        {"name": "ai_integration", "description": "LLM API integration (DeepSeek vision), prompt engineering"},
        {"name": "qa", "description": "testing, validation, edge cases"},
    ]
    engine = PlanningEngine(api_key=API_KEY)
    return await engine.plan(goal, agents)


async def research_suriname_market():
    """Researcher + Synthesizer: Suriname food delivery market."""
    manager = LLMAgent("mgr", "Research Director",
        "Decompose this research into 2-3 subtopics. Output JSON: "
        '{"subtasks": [{"worker": "researcher", "task": "..."}]}',
        api_key=API_KEY)
    researcher = LLMAgent("researcher", "Market Researcher",
        "You are an expert on Suriname's restaurant and food delivery market. "
        "Cover: market size, competitors, restaurant density in Paramaribo, WhatsApp commerce trends, "
        "Chinese restaurant ecosystem, B2B catering demand from corporates. Be thorough and factual.",
        api_key=API_KEY)
    synthesizer = LLMAgent("synthesizer", "Report Writer",
        "Synthesize findings into a structured report: Executive Summary, Market Size & Key Numbers, "
        "Competitive Landscape, WhatsApp Commerce Opportunity, B2B Catering Potential, "
        "Recommendations for SuriOrder. Be specific and actionable.",
        api_key=API_KEY)

    orch = MultiAgentOrchestrator()
    return await orch.run_team(
        team_id="research-market",
        agents={"mgr": manager, "researcher": researcher, "synthesizer": synthesizer},
        strategy=ManagerWorkerStrategy("mgr", ["researcher"]),
        initial_task={"prompt": "Research: Suriname food delivery market 2026. Focus on restaurant digitization, WhatsApp ordering trends, B2B catering demand, Chinese restaurant ecosystem."},
        blackboard=SharedBlackboard("research-market"),
    )


async def main():
    t_total = time.time()
    print(f"\n{'='*64}")
    print("  SURIORDER - MULTI-AGENT DEEP ANALYSIS")
    print(f"  6 analyses | DeepSeek API | {time.strftime('%H:%M:%S')}")
    print(f"{'='*64}")

    # -- Phase 1: Code Reviews (3 in sequence) --
    print("\n>>> PHASE 1/3: CODE REVIEWS (admin.js, orders.js, webhook.js)\n")

    reviews = []
    for name, path, focus in [
        ("admin.js", "src/routes/admin.js", "B2B billing logic, nuclear tab settlement, credit statements, dashboard stats aggregation"),
        ("orders.js", "src/routes/orders.js", "order placement flow, customer auto-upserts, WhatsApp notification triggers, cart validation"),
        ("webhook.js", "src/routes/webhook.js", "WhatsApp Cloud API webhook verification, message parsing, signature validation, rate limiting"),
    ]:
        t0 = time.time()
        result = await review_file(name, path, focus)
        elapsed = time.time() - t0
        reviews.append((name, result, elapsed))
        synthesis = result.get("synthesis", "")
        print(f"  [{name}] {elapsed:.1f}s")
        if synthesis:
            print(f"  {synthesis[:400]}")
        print()

    # -- Phase 2: Technical Debate --
    print(">>> PHASE 2/3: TECHNICAL DEBATE - SQLite vs PostgreSQL\n")

    t0 = time.time()
    debate_result = await debate_sqlite_vs_pg()
    debate_elapsed = time.time() - t0

    print(f"  Duration: {debate_elapsed:.1f}s")
    print(f"  Winner: {debate_result.get('winner', 'unknown')}")
    print(f"  Votes: {json.dumps(debate_result.get('votes', {}), indent=2)}")
    positions = debate_result.get("positions", {})
    for k, v in positions.items():
        label = k.replace("position/", "")
        print(f"  [{label}] {v[:300]}...")
    print()

    # -- Phase 3: Feature Planning + Market Research (parallel!) --
    print(">>> PHASE 3/3: FEATURE PLANNING + MARKET RESEARCH (parallel)\n")

    t0_plan = time.time()
    t0_research = time.time()

    plan_task = plan_ai_menu_feature()
    research_task = research_suriname_market()

    plan_result, research_result = await asyncio.gather(plan_task, research_task)
    plan_elapsed = time.time() - t0_plan
    research_elapsed = time.time() - t0_research

    # ── Plan output ──
    print(f"  [AI Menu Feature Plan] {plan_elapsed:.1f}s")
    print(f"  Goal: {plan_result.goal[:120]}...")
    print(f"  Steps ({len(plan_result.steps)} total):")
    for s in plan_result.steps:
        deps = f" (depends: {', '.join(s.dependencies)})" if s.dependencies else ""
        pg = f" [|| group {s.parallel_group}]" if s.parallel_group else ""
        print(f"    {s.step_id} -> {s.assigned_agent}{pg}{deps}: {s.description[:100]}")
    order = [s.step_id for s in plan_result.get_step_order()]
    print(f"  Execution: {' -> '.join(order)}")
    print()

    # ── Research output ──
    print(f"  [Market Research Report] {research_elapsed:.1f}s")
    synthesis = research_result.get("synthesis", "")
    if synthesis:
        print(f"  {synthesis[:2000]}")
    print()

    # ── FINAL SUMMARY ──
    total = time.time() - t_total
    print(f"{'='*64}")
    print(f"  ANALYSIS COMPLETE - {total:.0f}s total")
    print(f"  Files reviewed: 3 | Debate: 1 | Plan: 1 | Research: 1")
    print(f"  AI agents mobilized: 19 calls to DeepSeek API")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    asyncio.run(main())
