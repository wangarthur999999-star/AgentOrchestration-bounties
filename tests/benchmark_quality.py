"""Quality benchmark: multi-agent pipeline vs single-agent baseline.

Runs a set of customer messages through both approaches and produces
a side-by-side comparison across 4 quality dimensions:
  1. Accuracy — correctly addresses the customer's intent
  2. Tone — friendly, professional, natural
  3. CTA — includes clear next step
  4. Conciseness — 1-3 sentences, no robotic verbosity
"""

import asyncio
import json
import os
import time

from src.sdk.llm_agent import LLMAgent
from src.orchestrator.multi_agent import ManagerWorkerStrategy, MultiAgentOrchestrator

# ── Test messages covering 4 intents ──────────────────────────────────────

TEST_CASES = [
    {
        "id": "booking-1",
        "intent": "booking",
        "message": "Hi, I'd like to book a massage for tomorrow at 3pm. Swedish massage please.",
        "business": {"name": "Serenity Spa", "services": ["Swedish Massage", "Deep Tissue", "Hot Stone"]},
    },
    {
        "id": "inquiry-1",
        "intent": "inquiry",
        "message": "What are your prices for a deep tissue massage? And do you do couple sessions?",
        "business": {"name": "Serenity Spa", "services": ["Swedish Massage", "Deep Tissue", "Hot Stone", "Couples Massage"]},
    },
    {
        "id": "complaint-1",
        "intent": "complaint",
        "message": "I was at your spa yesterday and the therapist was 20 minutes late. Not happy about this.",
        "business": {"name": "Serenity Spa", "services": ["Swedish Massage", "Deep Tissue", "Facial"]},
    },
    {
        "id": "handoff-1",
        "intent": "handoff",
        "message": "Can I speak to the manager? I have a corporate event and need to discuss bulk pricing.",
        "business": {"name": "Serenity Spa", "services": ["Swedish Massage", "Deep Tissue", "Corporate Events"]},
    },
]

# ── Agent factory ─────────────────────────────────────────────────────────

def build_agents(api_key, base_url, model):
    templates = {
        "triage": {
            "id": "triage", "name": "Triage",
            "prompt": (
                "You are a customer service triage specialist. Classify incoming "
                "messages into: booking, inquiry, complaint, or handoff. "
                'Output JSON: {"intent": "...", "urgency": "low|medium|high", "summary": "..."}'
            ),
        },
        "specialist": {
            "id": "specialist", "name": "Specialist",
            "prompt": (
                "You are a customer service specialist for a local spa business. "
                "Be friendly, warm, and professional. Handle bookings (suggest time slots), "
                "inquiries (provide pricing), complaints (apologize and offer resolution), "
                "and handoffs (confirm owner will follow up). Keep responses concise."
            ),
        },
        "synthesizer": {
            "id": "synthesizer", "name": "Synthesizer",
            "prompt": (
                "You synthesize agent outputs into a natural, friendly customer response. "
                "1-3 sentences. Include a clear next step or call to action. "
                "Never sound robotic or template-like."
            ),
        },
    }
    agents = {}
    for cfg in templates.values():
        agents[cfg["id"]] = LLMAgent(
            agent_id=cfg["id"], name=cfg["name"],
            system_prompt=cfg["prompt"],
            api_key=api_key, base_url=base_url, model=model,
        )
    return agents


# ── Multi-agent pipeline ──────────────────────────────────────────────────

async def run_multi_agent(msg, biz_ctx, agents):
    biz_name = biz_ctx.get("name", "the business")
    services = biz_ctx.get("services", [])
    task_prompt = (
        f"Business: {biz_name}\n"
        f"Services: {', '.join(services)}\n"
        f"Customer message: {msg}\n\n"
        "1. Triage: classify the intent\n"
        "2. Specialist: draft a helpful response\n"
        "3. Synthesizer: produce the final customer-facing reply"
    )

    strategy = ManagerWorkerStrategy(
        manager_agent_id="triage", worker_agent_ids=["specialist"],
        synthesizer_agent_id="synthesizer", max_rounds=2,
    )
    orchestrator = MultiAgentOrchestrator()
    t0 = time.time()

    # Need fresh agents per run to avoid conversation history contamination
    result = await orchestrator.run_team(
        team_id=f"bench_{int(time.time() * 1000)}",
        agents=agents,
        strategy=strategy,
        initial_task={"prompt": task_prompt},
    )

    duration = round(time.time() - t0, 2)

    if result.get("status") != "completed":
        return {"response": f"ERROR: {result.get('error', 'unknown')}", "duration": duration}

    synthesis = result.get("synthesis", "")

    # Reset agents for next run
    for a in agents.values():
        a.reset_conversation()

    return {"response": synthesis, "duration": duration}


# ── Single-agent baseline ─────────────────────────────────────────────────

async def run_single_agent(msg, biz_ctx, agent):
    """Single LLM call — equivalent to the standard generateReply() path."""
    biz_name = biz_ctx.get("name", "the business")
    services = biz_ctx.get("services", [])
    prompt = (
        f"You are a customer service agent for {biz_name}. "
        f"Services: {', '.join(services)}. "
        f"Be friendly, professional, concise. 1-3 sentences.\n\n"
        f"Customer: {msg}\n\nYour reply:"
    )
    t0 = time.time()
    resp = await agent.handle_task({"prompt": prompt})
    agent.reset_conversation()
    return {"response": resp.get("output", ""), "duration": round(time.time() - t0, 2)}


# ── Evaluator LLM ─────────────────────────────────────────────────────────

async def evaluate(agent, test_case, ma_resp, sa_resp):
    """Have an LLM judge which response is better across 4 dimensions."""
    prompt = (
        f"Customer message: {test_case['message']}\n"
        f"Intent: {test_case['intent']}\n"
        f"Business: {test_case['business']['name']}\n\n"
        f"Response A (multi-agent): {ma_resp['response']}\n\n"
        f"Response B (single-agent): {sa_resp['response']}\n\n"
        "Compare A vs B on:\n"
        "1. Accuracy (correctly addresses intent): A / B / tie\n"
        "2. Tone (friendly, natural): A / B / tie\n"
        "3. CTA (clear next step): A / B / tie\n"
        "4. Conciseness (1-3 sentences, not robotic): A / B / tie\n"
        "5. Overall winner: A / B / tie\n\n"
        "Output JSON: {\"accuracy\": \"A|B|tie\", \"tone\": \"...\", "
        "\"cta\": \"...\", \"conciseness\": \"...\", \"overall\": \"A|B|tie\", "
        "\"comment\": \"one sentence explaining the overall verdict\"}"
    )
    resp = await agent.handle_task({"prompt": prompt})
    agent.reset_conversation()
    try:
        return json.loads(resp.get("output", "{}"))
    except json.JSONDecodeError:
        return {"overall": "tie", "comment": f"Parse error: {resp.get('output', '')[:100]}"}


# ── Main ──────────────────────────────────────────────────────────────────

async def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("AO_BASE_URL", "https://api.deepseek.com/v1")
    model = "deepseek-chat"

    if not api_key:
        print("DEEPSEEK_API_KEY not set")
        return

    # Evaluator uses its own agent
    eval_agent = LLMAgent(
        agent_id="evaluator", name="Evaluator",
        system_prompt="You are an impartial judge evaluating customer service responses. Output JSON only.",
        api_key=api_key, base_url=base_url, model=model,
    )
    await eval_agent.setup()

    single_agent = LLMAgent(
        agent_id="baseline", name="Baseline",
        system_prompt="You are a customer service agent. Be friendly, helpful, concise.",
        api_key=api_key, base_url=base_url, model=model,
    )
    await single_agent.setup()

    results = []
    ma_wins = sa_wins = ties = 0
    total_ma_time = total_sa_time = 0

    print("=" * 70)
    print("MULTI-AGENT vs SINGLE-AGENT QUALITY BENCHMARK")
    print("=" * 70)

    for tc in TEST_CASES:
        # Fresh agents per test case to avoid cross-contamination
        ma_agents = build_agents(api_key, base_url, model)

        # Run both approaches
        ma_resp = await run_multi_agent(tc["message"], tc["business"], ma_agents)
        sa_resp = await run_single_agent(tc["message"], tc["business"], single_agent)

        total_ma_time += ma_resp["duration"]
        total_sa_time += sa_resp["duration"]

        # Evaluate
        eval_result = await evaluate(eval_agent, tc, ma_resp, sa_resp)

        winner = eval_result.get("overall", "tie")
        if winner == "A": ma_wins += 1
        elif winner == "B": sa_wins += 1
        else: ties += 1

        print(f"\n── {tc['id']} ({tc['intent']}) ──────────────────────────────")
        print(f"Customer: {tc['message'][:100]}")
        print(f"\nMulti-agent ({ma_resp['duration']}s):  {ma_resp['response'][:200]}")
        print(f"Single-agent ({sa_resp['duration']}s): {sa_resp['response'][:200]}")
        print(f"\nVerdict: {eval_result.get('overall', '?').upper()}")
        print(f"  Accuracy: {eval_result.get('accuracy', '?')} | Tone: {eval_result.get('tone', '?')} | "
              f"CTA: {eval_result.get('cta', '?')} | Concise: {eval_result.get('conciseness', '?')}")
        print(f"  Comment: {eval_result.get('comment', 'N/A')}")

        results.append({"id": tc["id"], "eval": eval_result, "ma_time": ma_resp["duration"], "sa_time": sa_resp["duration"]})

    print(f"\n{'=' * 70}")
    print(f"SUMMARY: Multi-agent wins: {ma_wins} | Single-agent wins: {sa_wins} | Ties: {ties}")
    print(f"Avg multi-agent time:  {total_ma_time / len(TEST_CASES):.1f}s")
    print(f"Avg single-agent time: {total_sa_time / len(TEST_CASES):.1f}s")
    print(f"Multi-agent overhead:  {total_ma_time / max(total_sa_time, 0.01):.1f}x slower")
    print(f"{'=' * 70}")

    # Save results
    with open("benchmark_results.json", "w") as f:
        json.dump({"results": results, "ma_wins": ma_wins, "sa_wins": sa_wins, "ties": ties}, f, indent=2)
    print("\nResults saved to benchmark_results.json")


if __name__ == "__main__":
    asyncio.run(main())
