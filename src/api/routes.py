"""API route definitions."""

import asyncio
import json
import logging
import os
import time
from typing import List, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.agent import AgentRegistry, AgentStatus
from src.sdk.llm_agent import LLMAgent
from src.orchestrator.multi_agent import (
    ManagerWorkerStrategy,
    MultiAgentOrchestrator,
)

logger = logging.getLogger(__name__)
router = APIRouter()
registry = AgentRegistry()

# ---------------------------------------------------------------------------
# Multi-agent team response models
# ---------------------------------------------------------------------------

class CustomerMessage(BaseModel):
    customer_message: str
    business_context: dict = {}
    language: str = "en"
    conversation_history: list[dict] = []


class TeamResponse(BaseModel):
    status: str
    response: str = ""
    agents_used: list[str] = []
    duration: float = 0.0
    error: str = ""


# Pre-built agent templates for customer service
CUSTOMER_SERVICE_AGENTS = {
    "triage": {
        "id": "triage",
        "name": "Triage Agent",
        "prompt": (
            "You are a customer service triage specialist. Classify incoming messages into: "
            "booking (appointment/reservation requests), inquiry (pricing/service questions), "
            "complaint (issues/problems), or handoff (needs human). "
            "Output JSON: {\"intent\": \"...\", \"urgency\": \"low|medium|high\", \"summary\": \"...\"}"
        ),
    },
    "specialist": {
        "id": "specialist",
        "name": "Service Specialist",
        "prompt": (
            "You are a customer service specialist for a local business. "
            "You handle inquiries about services, pricing, availability, and bookings. "
            "Be friendly, concise, and professional. Use the business context provided. "
            "If asked about booking, suggest a specific time slot. "
            "If you don't know something, offer to connect the customer with the owner."
        ),
    },
    "synthesizer": {
        "id": "synthesizer",
        "name": "Response Synthesizer",
        "prompt": (
            "You synthesize multiple agent outputs into a single, natural customer response. "
            "Keep it friendly and conversational — NOT robotic. "
            "Match the customer's language. Use the business's tone. "
            "Include a clear next step or CTA. 1-3 sentences max. "
            "Output ONLY the final reply — no preamble, no commentary."
        ),
    },
}


def _build_cs_agents(api_key: str, base_url: str, model: str, lang: str = "en") -> dict[str, LLMAgent]:
    """Build the customer service agent team."""
    agents = {}
    for role, cfg in CUSTOMER_SERVICE_AGENTS.items():
        prompt = cfg["prompt"]
        if lang and lang != "en":
            prompt += f"\nIMPORTANT: Respond in {lang}."
        agents[cfg["id"]] = LLMAgent(
            agent_id=cfg["id"],
            name=cfg["name"],
            system_prompt=prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    return agents


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


@router.post("/teams/respond", response_model=TeamResponse)
async def team_respond(msg: CustomerMessage) -> TeamResponse:
    """Handle a customer message with a multi-agent customer service team.

    Spins up a Triage → Specialist → Synthesizer pipeline to produce
    a high-quality response for complex customer inquiries.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("AO_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("AO_MODEL", "deepseek-chat")

    if not api_key:
        return TeamResponse(status="error", error="DEEPSEEK_API_KEY not configured")

    t0 = time.time()

    try:
        biz_ctx = msg.business_context or {}
        biz_name = biz_ctx.get("name", "the business")
        services = biz_ctx.get("services", [])
        lang = msg.language or biz_ctx.get("language", "en")

        # Build prompt with full context
        history_str = ""
        if msg.conversation_history:
            entries = msg.conversation_history[-6:]  # last 6 messages
            history_str = "Recent conversation:\n" + "\n".join(
                f"  [{h.get('role', '?')}]: {h.get('content', '')[:200]}"
                for h in entries
            ) + "\n\n"

        task_prompt = (
            f"Business: {biz_name}\n"
            f"Services: {', '.join(services) if services else 'general services'}\n"
            f"Customer language: {lang}\n\n"
            f"{history_str}"
            f"Customer message: {msg.customer_message}\n\n"
            "1. Triage: classify the intent\n"
            "2. Specialist: draft a helpful response\n"
            "3. Synthesizer: produce the final customer-facing reply"
        )

        agents = _build_cs_agents(api_key, base_url, model, lang)
        strategy = ManagerWorkerStrategy(
            manager_agent_id="triage",
            worker_agent_ids=["specialist"],
            synthesizer_agent_id="synthesizer",
            max_rounds=2,
        )
        orchestrator = MultiAgentOrchestrator()
        team_id = f"cs_{int(time.time())}"

        result = await orchestrator.run_team(
            team_id=team_id,
            agents=agents,
            strategy=strategy,
            initial_task={"prompt": task_prompt},
        )

        if result.get("status") in ("failed", "timeout"):
            return TeamResponse(
                status="error",
                error=f"Orchestrator: {result.get('error', 'unknown')}",
                duration=round(time.time() - t0, 2),
            )

        synthesis = result.get("synthesis", "")

        return TeamResponse(
            status=result.get("status", "error"),
            response=synthesis,
            agents_used=["triage", "specialist", "synthesizer"],
            duration=round(time.time() - t0, 2),
        )

    except Exception as e:
        logger.exception("Multi-agent team failed")
        return TeamResponse(
            status="error",
            error=str(e),
            duration=round(time.time() - t0, 2),
        )

# 2019-03-18T11:10:18 update

# 2019-04-22T13:58:05 update

# 2019-05-28T08:52:40 update

# 2019-06-13T19:27:11 update

# 2019-06-25T18:52:04 update

# 2019-06-26T17:23:40 update

# 2019-07-24T12:38:12 update

# 2019-08-06T17:13:22 update

# 2019-09-26T19:27:40 update

# 2019-11-08T15:48:07 update

# 2019-12-05T16:07:01 update

# 2020-01-17T17:50:06 update

# 2020-04-24T17:12:53 update

# 2020-07-21T19:32:14 update

# 2020-07-21T20:23:54 update

# 2020-08-14T20:37:18 update

# 2020-11-05T16:47:32 update

# 2021-03-11T12:52:51 update

# 2021-03-15T12:40:28 update

# 2021-03-19T19:24:45 update

# 2021-05-07T14:43:25 update

# 2021-05-12T12:11:05 update

# 2021-05-26T19:45:39 update

# 2021-06-29T19:14:28 update

# 2021-07-09T17:57:49 update

# 2021-07-19T08:20:34 update

# 2021-07-23T15:35:00 update

# 2021-07-26T09:55:35 update

# 2021-11-01T20:50:23 update

# 2022-02-04T09:23:08 update

# 2022-02-14T15:58:17 update

# 2022-02-28T09:52:05 update

# 2022-05-19T16:28:06 update

# 2022-05-30T15:01:44 update

# 2022-07-31T11:24:57 update

# 2022-08-09T15:47:57 update

# 2022-08-19T12:51:59 update

# 2022-11-02T08:06:45 update

# 2022-11-21T14:12:56 update

# 2023-01-13T12:25:51 update

# 2023-03-31T14:11:34 update

# 2023-04-03T20:57:22 update

# 2023-04-28T19:01:38 update

# 2023-07-18T16:47:22 update

# 2023-09-28T18:50:58 update

# 2023-10-02T13:22:15 update

# 2023-10-23T10:46:19 update

# 2023-11-02T16:52:55 update

# 2023-12-08T17:38:20 update

# 2023-12-11T10:59:19 update

# 2024-01-15T16:27:41 update

# 2024-02-09T11:56:21 update

# 2024-02-15T16:47:43 update

# 2024-03-26T08:08:33 update

# 2024-07-11T15:59:46 update

# 2024-09-04T17:13:05 update

# 2024-09-20T11:28:38 update

# 2024-12-02T16:42:53 update

# 2025-01-15T12:12:38 update

# 2025-02-05T09:08:36 update

# 2025-05-16T19:40:31 update

# 2025-06-13T13:20:50 update

# 2025-08-13T12:22:26 update

# 2025-09-01T12:30:44 update

# 2025-11-06T12:23:44 update

# 2025-12-26T08:40:45 update

# 2026-04-08T19:23:48 update

# 2026-04-09T20:30:37 update

# 2026-05-13T11:36:25 update
