"""Round 2: Product strategy & business analysis for SuriOrder."""
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

SEP = "=" * 64


async def debate_pricing():
    """Debate: commission vs flat fee for B2B catering."""
    agents = {
        "commission": LLMAgent("commission", "Commission Advocate",
            "Argue for 10-15% commission on B2B catering orders. Focus on: aligned incentives "
            "(you only make money when restaurants make money), no upfront friction for restaurants, "
            "scales with order volume, restaurants prefer pay-as-you-go. SuriOrder is free SaaS. "
            "Keep under 120 words. Suriname context.",
            api_key=API_KEY),
        "flat_fee": LLMAgent("flat_fee", "Flat Fee Advocate",
            "Argue for monthly flat fee (SRD 500-2000/month). Focus on: predictable revenue, "
            "simpler billing, no need to verify order amounts, restaurants hate variable costs, "
            "easier to position as 'premium B2B tier', restaurants can budget. "
            "Keep under 120 words. Suriname context.",
            api_key=API_KEY),
        "hybrid": LLMAgent("hybrid", "Hybrid Strategist",
            "Propose a hybrid approach: free tier for basic ordering + paid B2B tier with "
            "flat monthly + small transaction fee. Consider Suriname market: Chinese restaurant "
            "owners are price-sensitive, corporate clients want predictability. Vote and explain. "
            "Keep under 150 words.",
            api_key=API_KEY),
    }
    orch = MultiAgentOrchestrator()
    return await orch.run_team(
        team_id="debate-pricing",
        agents=agents,
        strategy=DebateStrategy(debate_topic="Commission vs flat fee vs hybrid for SuriOrder B2B catering revenue model", max_rounds=2),
        initial_task={"prompt": "Debate: pricing model for SuriOrder B2B catering"},
        blackboard=SharedBlackboard("debate-pricing"),
    )


async def plan_feature_roadmap():
    """Plan: next 3-month feature roadmap."""
    goal = (
        "Create a 3-month feature roadmap for SuriOrder, a free ordering SaaS for Suriname "
        "restaurants. Current state: 41 tests, deployed on Render free tier, WhatsApp webhook "
        "integration, B2B customer profiling and credit statements working, 4 languages (nl/en/zh/es). "
        "Business model: free SaaS -> B2B catering commission -> own-brand pickup points. "
        "Prioritize features that: (1) increase restaurant adoption, (2) enable first B2B revenue, "
        "(3) strengthen the data moat. No AI features."
    )
    agents = [
        {"name": "product_manager", "description": "prioritizes features by business impact and feasibility"},
        {"name": "backend_dev", "description": "Node.js/Express/SQLite backend, estimates technical complexity"},
        {"name": "growth_hacker", "description": "restaurant acquisition, viral loops, WhatsApp marketing"},
        {"name": "b2b_specialist", "description": "corporate catering sales, B2B onboarding, invoicing"},
    ]
    engine = PlanningEngine(api_key=API_KEY)
    return await engine.plan(goal, agents)


async def research_whatsapp_strategy():
    """Research: WhatsApp commerce best practices for developing markets."""
    manager = LLMAgent("mgr", "Research Director",
        "Decompose into 2-3 subtopics about WhatsApp commerce. Output JSON: "
        '{"subtasks": [{"worker": "researcher", "task": "..."}]}',
        api_key=API_KEY)
    researcher = LLMAgent("researcher", "WhatsApp Commerce Researcher",
        "Research WhatsApp Business Platform best practices for restaurant ordering in developing "
        "markets similar to Suriname. Cover: WhatsApp catalog features, message template strategies, "
        "automated order confirmation flows, broadcast list usage, click-to-WhatsApp ads, "
        "payment integration via WhatsApp, and case studies of WhatsApp-first restaurant businesses "
        "in Southeast Asia, Africa, and Latin America. Be specific.",
        api_key=API_KEY)
    synthesizer = LLMAgent("synthesizer", "Strategy Writer",
        "Synthesize into an actionable WhatsApp growth playbook for SuriOrder. Structure: "
        "1) Quick wins (1-2 weeks to implement), 2) Growth engines (1-2 months), "
        "3) Moats (long-term advantages). Be specific with WhatsApp API features and Suriname context.",
        api_key=API_KEY)

    orch = MultiAgentOrchestrator()
    return await orch.run_team(
        team_id="research-wa",
        agents={"mgr": manager, "researcher": researcher, "synthesizer": synthesizer},
        strategy=ManagerWorkerStrategy("mgr", ["researcher"]),
        initial_task={"prompt": "Research: WhatsApp commerce strategy for restaurant ordering in developing markets. Apply to SuriOrder's Suriname context."},
        blackboard=SharedBlackboard("research-wa"),
    )


async def debate_architecture():
    """Debate: scaling path from free tier."""
    agents = {
        "stay_lean": LLMAgent("stay_lean", "Lean Advocate",
            "Argue to stay on single server + SQLite as long as possible. SuriOrder serves a "
            "country of 600K people, not 60M. Render free tier + better-sqlite3 WAL mode can "
            "handle thousands of orders/day. Premature scaling kills startups. Focus on product-market "
            "fit first, scale only when you have paying B2B customers. Keep under 120 words.",
            api_key=API_KEY),
        "prepare_scale": LLMAgent("prepare_scale", "Scale Advocate",
            "Argue to prepare scaling path NOW: extract DB layer behind repository pattern, "
            "add Redis for session/rate-limit, containerize for easy migration off Render free tier. "
            "B2B customers expect reliability. A 15-min cold start on Render free tier is unacceptable "
            "for corporate clients ordering lunch for 50 people. Keep under 120 words.",
            api_key=API_KEY),
        "architect": LLMAgent("architect", "Systems Architect",
            "Evaluate the tradeoff for SuriOrder: single-country market, early B2B, free-tier hosting. "
            "What's the right scaling posture NOW vs what can wait? Vote with specific rationale. "
            "Keep under 150 words.",
            api_key=API_KEY),
    }
    orch = MultiAgentOrchestrator()
    return await orch.run_team(
        team_id="debate-arch",
        agents=agents,
        strategy=DebateStrategy(debate_topic="Should SuriOrder invest in scaling architecture now or stay lean?", max_rounds=2),
        initial_task={"prompt": "Debate: scaling architecture strategy for SuriOrder"},
        blackboard=SharedBlackboard("debate-arch"),
    )


async def main():
    t_total = time.time()
    print(f"\n{'='*64}")
    print("  SURIORDER ROUND 2 - PRODUCT STRATEGY & BUSINESS")
    print(f"  4 analyses | DeepSeek API | {time.strftime('%H:%M:%S')}")
    print(f"{'='*64}\n")

    # --- Debate 1: Pricing Model ---
    print(">>> 1/4: PRICING MODEL DEBATE (Commission vs Flat Fee vs Hybrid)\n")
    t0 = time.time()
    r = await debate_pricing()
    print(f"  Duration: {time.time()-t0:.1f}s | Winner: {r.get('winner','?')}")
    votes = r.get('votes', {})
    for agent_id, voted_for in votes.items():
        print(f"    {agent_id} -> {voted_for}")
    positions = r.get('positions', {})
    for k, v in positions.items():
        label = k.replace("position/", "")
        print(f"  [{label}] {v[:350]}...")
    print()

    # --- Feature Roadmap Planning ---
    print(">>> 2/4: FEATURE ROADMAP PLANNING (Next 3 Months)\n")
    t0 = time.time()
    plan = await plan_feature_roadmap()
    print(f"  Duration: {time.time()-t0:.1f}s")
    print(f"  Goal: {plan.goal[:100]}...")
    print(f"  Steps ({len(plan.steps)}):")
    for s in plan.steps:
        deps = f" (after: {', '.join(s.dependencies)})" if s.dependencies else ""
        pg = f" [|| {s.parallel_group}]" if s.parallel_group else ""
        print(f"    {s.step_id} -> {s.assigned_agent}{pg}{deps}")
        print(f"      {s.description[:130]}")
    order = [s.step_id for s in plan.get_step_order()]
    print(f"  Order: {' -> '.join(order)}")
    print()

    # --- WhatsApp Strategy Research ---
    print(">>> 3/4: WHATSAPP COMMERCE STRATEGY RESEARCH\n")
    t0 = time.time()
    r = await research_whatsapp_strategy()
    print(f"  Duration: {time.time()-t0:.1f}s")
    synthesis = r.get("synthesis", "")
    if synthesis:
        print(f"  {synthesis[:2000]}")
    print()

    # --- Debate 2: Architecture Scaling ---
    print(">>> 4/4: ARCHITECTURE SCALING DEBATE (Stay Lean vs Prepare Now)\n")
    t0 = time.time()
    r = await debate_architecture()
    print(f"  Duration: {time.time()-t0:.1f}s | Winner: {r.get('winner','?')}")
    for agent_id, voted_for in r.get('votes', {}).items():
        print(f"    {agent_id} -> {voted_for}")
    for k, v in r.get('positions', {}).items():
        label = k.replace("position/", "")
        print(f"  [{label}] {v[:350]}...")
    print()

    # --- Summary ---
    total = time.time() - t_total
    print(f"{'='*64}")
    print(f"  ROUND 2 COMPLETE - {total:.0f}s | 4 strategic analyses")
    print(f"{'='*64}\n")


if __name__ == "__main__":
    asyncio.run(main())
