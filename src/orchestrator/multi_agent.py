"""Multi-Agent Orchestrator — conversation strategies and team coordination."""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from src.orchestrator.approval import ApprovalGateway, ApprovalStatus
from src.orchestrator.memory import SharedBlackboard
from src.orchestrator.protocol import AgentMessage, MessageBus, MessageType
from src.sdk.llm_agent import LLMAgent

logger = logging.getLogger(__name__)

TERMINATION_TOKEN = "###TERMINATE###"
MAX_TEAM_TIMEOUT = 600  # 10 minutes


class ConversationStrategy(ABC):
    """Base class for multi-agent conversation patterns."""

    def __init__(
        self,
        max_rounds: int = 10,
        timeout: float = MAX_TEAM_TIMEOUT,
        approval_gateway: Optional[ApprovalGateway] = None,
    ):
        self.max_rounds = max_rounds
        self.timeout = timeout
        self.approval_gateway = approval_gateway

    @abstractmethod
    async def execute(
        self,
        agents: dict[str, LLMAgent],
        blackboard: SharedBlackboard,
        bus: MessageBus,
        initial_task: dict,
    ) -> dict:
        """Execute the strategy with the given agents. Returns results dict."""
        ...

    async def _request_approval(
        self, agent_id: str, action: str, reasoning: str,
        context: dict = None, timeout: float = None,
    ) -> bool:
        """Convenience — return True if approved, False otherwise."""
        if self.approval_gateway is None:
            return True
        resp = await self.approval_gateway.ask(
            agent_id=agent_id, action=action, reasoning=reasoning,
            context=context, timeout=timeout,
        )
        return resp.status in (ApprovalStatus.APPROVED, ApprovalStatus.MODIFIED)


class RoundRobinStrategy(ConversationStrategy):
    """Fixed-order turn taking. Each agent processes the previous output."""

    def __init__(self, agent_order: Optional[list[str]] = None, max_rounds: int = 3):
        super().__init__(max_rounds=max_rounds)
        self.agent_order = agent_order or []

    async def execute(
        self, agents: dict[str, LLMAgent], blackboard: SharedBlackboard,
        bus: MessageBus, initial_task: dict,
    ) -> dict:
        order = self.agent_order or list(agents.keys())
        team_id = blackboard.team_id
        prev_output = initial_task.get("prompt", str(initial_task))
        blackboard.put("input", prev_output, "system")

        for round_num in range(self.max_rounds):
            for agent_id in order:
                if agent_id not in agents:
                    continue
                agent = agents[agent_id]
                prompt = prev_output if round_num == 0 and agent_id == order[0] else (
                    f"Previous agent output:\n{prev_output}\n\n"
                    f"Task: {initial_task.get('prompt', 'Continue processing')}"
                )
                msg = AgentMessage(
                    type=MessageType.TASK,
                    from_agent="system",
                    to_agent=agent_id,
                    team_id=team_id,
                    payload={"prompt": prompt},
                )
                response = await agent.handle_message(msg)
                prev_output = response.payload.get("content", "")
                blackboard.put(agent_id, prev_output, agent_id)

        return {"status": "completed", "blackboard": blackboard.snapshot()}


class GroupChatStrategy(ConversationStrategy):
    """LLM-driven speaker selection. Agents see full transcript, LLM picks speaker."""

    def __init__(
        self, speaker_selector_llm: Optional[Callable] = None,
        max_rounds: int = 10,
    ):
        super().__init__(max_rounds=max_rounds)
        self._speaker_selector = speaker_selector_llm

    async def _select_speaker(
        self, agents: dict[str, LLMAgent], history: list[dict], task: str,
    ) -> str:
        if self._speaker_selector:
            return await self._speaker_selector(agents, history, task)
        # Default: simple round-robin among available agents
        agent_ids = list(agents.keys())
        spoke_count = sum(1 for h in history if h.get("agent") in agent_ids)
        return agent_ids[spoke_count % len(agent_ids)]

    async def execute(
        self, agents: dict[str, LLMAgent], blackboard: SharedBlackboard,
        bus: MessageBus, initial_task: dict,
    ) -> dict:
        team_id = blackboard.team_id
        task_prompt = initial_task.get("prompt", str(initial_task))
        history: list[dict] = []
        agent_ids = list(agents.keys())

        # Send the initial task as a broadcast
        init_msg = AgentMessage(
            type=MessageType.BROADCAST,
            from_agent="system",
            team_id=team_id,
            payload={"prompt": task_prompt, "agents": agent_ids},
        )
        bus.broadcast(init_msg)

        for _ in range(self.max_rounds):
            speaker_id = await self._select_speaker(agents, history, task_prompt)
            if speaker_id not in agents:
                break

            agent = agents[speaker_id]
            transcript = json.dumps(history, ensure_ascii=False)
            msg = AgentMessage(
                type=MessageType.TASK,
                from_agent="system",
                to_agent=speaker_id,
                team_id=team_id,
                payload={
                    "prompt": f"Conversation so far:\n{transcript}\n\n"
                              f"Your turn. Task: {task_prompt}\n"
                              f"Reply with your input. Say '{TERMINATION_TOKEN}' if done.",
                },
            )
            response = await agent.handle_message(msg)
            content = response.payload.get("content", "")
            history.append({"agent": speaker_id, "name": agent.name, "content": content})
            blackboard.put(speaker_id, content, speaker_id)

            if TERMINATION_TOKEN in content:
                break

        return {"status": "completed", "history": history, "blackboard": blackboard.snapshot()}


class DebateStrategy(ConversationStrategy):
    """Agents debate a proposition, then vote. Majority or tiebreaker decides."""

    def __init__(self, debate_topic: str, voting_threshold: float = 0.5, max_rounds: int = 5):
        super().__init__(max_rounds=max_rounds)
        self.debate_topic = debate_topic
        self.voting_threshold = voting_threshold

    async def execute(
        self, agents: dict[str, LLMAgent], blackboard: SharedBlackboard,
        bus: MessageBus, initial_task: dict,
    ) -> dict:
        team_id = blackboard.team_id
        topic = self.debate_topic or initial_task.get("prompt", "")
        agent_ids = list(agents.keys())

        for round_num in range(self.max_rounds):
            positions = {}

            # All agents process the same debate topic in parallel
            async def get_position(aid: str) -> tuple[str, str]:
                agent = agents[aid]
                prior_positions = blackboard.get_all()
                context = f"Debate topic: {topic}\n"
                if prior_positions:
                    context += f"Prior positions:\n{json.dumps(prior_positions, indent=2)}\n"
                context += f"\nRound {round_num + 1}: State your position."

                msg = AgentMessage(
                    type=MessageType.QUERY,
                    from_agent="system",
                    to_agent=aid,
                    team_id=team_id,
                    payload={"prompt": context},
                )
                response = await agent.handle_message(msg)
                return aid, response.payload.get("content", "")

            tasks = [get_position(aid) for aid in agent_ids]
            results = await asyncio.gather(*tasks)
            for aid, pos in results:
                positions[aid] = pos
                blackboard.put(f"position/{aid}", pos, aid)

            # Check for consensus
            if self._evaluate_consensus(positions, agents):
                break

        # Voting phase
        votes = await self._collect_votes(agents, topic, blackboard, bus)
        winner = self._tally_votes(votes, list(agents.keys()))

        return {
            "status": "completed",
            "topic": topic,
            "positions": blackboard.get_all("position/"),
            "votes": votes,
            "winner": winner,
        }

    async def _collect_votes(
        self, agents: dict[str, LLMAgent], topic: str,
        blackboard: SharedBlackboard, bus: MessageBus,
    ) -> dict[str, str]:
        """Each agent casts a vote."""
        votes = {}
        for aid, agent in agents.items():
            positions = blackboard.get_all("position/")
            vote_prompt = (
                f"Topic: {topic}\n\nPositions:\n{json.dumps(positions, indent=2)}\n\n"
                "Vote for the best position. Reply with just the agent name."
            )
            msg = AgentMessage(
                type=MessageType.VOTE,
                from_agent="system",
                to_agent=aid,
                team_id=blackboard.team_id,
                payload={"prompt": vote_prompt},
            )
            response = await agent.handle_message(msg)
            votes[aid] = response.payload.get("content", "").strip()
        return votes

    def _evaluate_consensus(self, positions: dict, agents: dict) -> bool:
        """Simple heuristic: if all positions share key phrases, we have consensus."""
        if len(positions) < 2:
            return True
        values = list(positions.values())
        for v in values[1:]:
            overlap = len(set(values[0].lower().split()) & set(v.lower().split()))
            if overlap < 3:
                return False
        return True

    def _tally_votes(
        self, votes: dict[str, str], agent_ids: list[str],
    ) -> str:
        """Count votes, return the winner."""
        counts: dict[str, int] = {}
        for voted_for in votes.values():
            for aid in agent_ids:
                if aid in voted_for or voted_for in aid:
                    counts[aid] = counts.get(aid, 0) + 1
        if not counts:
            return agent_ids[0] if agent_ids else ""
        return max(counts, key=lambda k: counts[k])


class ManagerWorkerStrategy(ConversationStrategy):
    """Manager decomposes task, workers process in parallel, manager synthesizes.

    Subtasks can include 'require_approval: true' to trigger human-in-the-loop
    before the worker executes.
    """

    def __init__(
        self, manager_agent_id: str, worker_agent_ids: list[str],
        max_rounds: int = 3, approval_gateway: Optional[ApprovalGateway] = None,
        synthesizer_agent_id: str = "",
    ):
        super().__init__(max_rounds=max_rounds, approval_gateway=approval_gateway)
        self.manager_id = manager_agent_id
        self.worker_ids = worker_agent_ids
        self.synthesizer_id = synthesizer_agent_id

    async def execute(
        self, agents: dict[str, LLMAgent], blackboard: SharedBlackboard,
        bus: MessageBus, initial_task: dict,
    ) -> dict:
        team_id = blackboard.team_id
        manager = agents.get(self.manager_id)
        if not manager:
            return {"status": "failed", "error": f"Manager agent {self.manager_id} not found"}

        task_prompt = initial_task.get("prompt", str(initial_task))

        # Step 1: Manager decomposes the task
        approval_hint = ""
        if self.approval_gateway:
            approval_hint = (
                "For sensitive actions (sending emails, making payments, deploying code, "
                "modifying production data), set \"require_approval\": true for that subtask. "
            )
        decompose_prompt = (
            f"Goal: {task_prompt}\n\n"
            f"You have {len(self.worker_ids)} workers: {', '.join(self.worker_ids)}.\n"
            f"{approval_hint}"
            "Decompose this goal into subtasks, one per worker. "
            "Output JSON: {{\"subtasks\": [{{\"worker\": \"worker_id\", \"task\": \"description\", "
            "\"require_approval\": false}}]}}"
        )
        decompose_msg = AgentMessage(
            type=MessageType.TASK,
            from_agent="system",
            to_agent=self.manager_id,
            team_id=team_id,
            payload={"prompt": decompose_prompt},
        )
        decompose_resp = await manager.handle_message(decompose_msg)
        subtasks, approval_flags = self._parse_subtasks(
            decompose_resp.payload.get("content", "{}"), self.worker_ids, task_prompt
        )

        # Step 2: Workers process subtasks in parallel, with optional approval
        async def run_worker(worker_id: str, task_desc: str) -> tuple[str, str]:
            # Check for human approval before executing
            if approval_flags.get(worker_id, False) and self.approval_gateway:
                approved = await self._request_approval(
                    agent_id=worker_id,
                    action=f"Execute: {task_desc[:120]}",
                    reasoning=f"Worker {worker_id} assigned to: {task_desc}",
                    context={"worker_id": worker_id, "task": task_desc},
                )
                if not approved:
                    return worker_id, f"REJECTED: Human denied execution of '{task_desc[:80]}'"

            worker = agents.get(worker_id)
            if not worker:
                return worker_id, f"Error: agent {worker_id} not found"
            msg = AgentMessage(
                type=MessageType.TASK,
                from_agent=self.manager_id,
                to_agent=worker_id,
                team_id=team_id,
                payload={"prompt": task_desc},
            )
            resp = await worker.handle_message(msg)
            result = resp.payload.get("content", "")
            blackboard.put(f"worker/{worker_id}", result, worker_id)
            return worker_id, result

        worker_tasks = [
            run_worker(wid, subtasks.get(wid, task_prompt))
            for wid in self.worker_ids if wid in agents
        ]
        worker_results = dict(await asyncio.gather(*worker_tasks))

        # Step 3: Synthesize results (use dedicated synthesizer if provided)
        synth_agent_id = self.synthesizer_id or self.manager_id
        synth_agent = agents.get(synth_agent_id, manager)
        synthesis_prompt = (
            f"Original goal: {task_prompt}\n\nWorker outputs:\n"
            f"{json.dumps(worker_results, indent=2)}\n\n"
            "Synthesize these results into a final answer. Be comprehensive."
        )
        synth_msg = AgentMessage(
            type=MessageType.TASK,
            from_agent="system",
            to_agent=synth_agent_id,
            team_id=team_id,
            payload={"prompt": synthesis_prompt},
        )
        synth_resp = await synth_agent.handle_message(synth_msg)

        return {
            "status": "completed",
            "manager": self.manager_id,
            "worker_results": worker_results,
            "synthesis": synth_resp.payload.get("content", ""),
            "blackboard": blackboard.snapshot(),
        }

    def _parse_subtasks(
        self, raw: str, worker_ids: list[str], fallback_task: str,
    ) -> tuple[dict[str, str], dict[str, bool]]:
        """Parse manager's decomposition JSON. Returns (tasks, approval_flags)."""
        approval_flags: dict[str, bool] = {}
        try:
            data = json.loads(raw)
            parsed = {}
            for st in data.get("subtasks", []):
                wid = st.get("worker", "")
                if wid in worker_ids:
                    parsed[wid] = st.get("task", fallback_task)
                    approval_flags[wid] = st.get("require_approval", False)
            for wid in worker_ids:
                if wid not in parsed:
                    parsed[wid] = fallback_task
                    approval_flags[wid] = False
            return parsed, approval_flags
        except json.JSONDecodeError:
            return {wid: fallback_task for wid in worker_ids}, {wid: False for wid in worker_ids}


class HybridStrategy(ManagerWorkerStrategy):
    """Manager decomposes, workers execute via sub-strategies (Debate, RoundRobin, etc.).

    Each worker slot can be backed by a team of sub-agents running a specific
    conversation strategy. Workers without a sub-strategy fall back to direct
    single-agent LLM response.
    """

    def __init__(
        self,
        manager_agent_id: str,
        worker_agent_ids: list[str],
        worker_strategies: dict[str, ConversationStrategy] = None,
        worker_sub_agents: dict[str, dict[str, LLMAgent]] = None,
        max_rounds: int = 3,
    ):
        super().__init__(manager_agent_id, worker_agent_ids, max_rounds)
        self.worker_strategies = worker_strategies or {}
        self.worker_sub_agents = worker_sub_agents or {}

    async def execute(
        self, agents: dict[str, LLMAgent], blackboard: SharedBlackboard,
        bus: MessageBus, initial_task: dict,
    ) -> dict:
        team_id = blackboard.team_id
        manager = agents.get(self.manager_id)
        if not manager:
            return {"status": "failed", "error": f"Manager agent {self.manager_id} not found"}

        task_prompt = initial_task.get("prompt", str(initial_task))

        # Step 1: Manager decomposes
        decompose_prompt = (
            f"Goal: {task_prompt}\n\n"
            f"You have {len(self.worker_ids)} workers: {', '.join(self.worker_ids)}.\n"
            "Decompose this goal into subtasks, one per worker. "
            "Output JSON: {{\"subtasks\": [{{\"worker\": \"worker_id\", \"task\": \"description\"}}]}}"
        )
        decompose_msg = AgentMessage(
            type=MessageType.TASK,
            from_agent="system",
            to_agent=self.manager_id,
            team_id=team_id,
            payload={"prompt": decompose_prompt},
        )
        decompose_resp = await manager.handle_message(decompose_msg)
        subtasks, _approval_flags = self._parse_subtasks(
            decompose_resp.payload.get("content", "{}"), self.worker_ids, task_prompt
        )

        # Step 2: Workers process — each may use a sub-strategy
        async def run_worker(worker_id: str, task_desc: str) -> tuple[str, str]:
            strategy = self.worker_strategies.get(worker_id)
            sub_agents = self.worker_sub_agents.get(worker_id)

            if strategy and sub_agents:
                sub_bb = SharedBlackboard(f"{team_id}/{worker_id}")
                sub_bus = MessageBus()
                orchestrator = MultiAgentOrchestrator(sub_bus)
                sub_result = await orchestrator.run_team(
                    team_id=f"{team_id}/{worker_id}",
                    agents=sub_agents,
                    strategy=strategy,
                    initial_task={"prompt": task_desc},
                    blackboard=sub_bb,
                )
                output = sub_result.get("synthesis", sub_result.get("status", str(sub_result)))
                if isinstance(output, dict):
                    output = json.dumps(output, ensure_ascii=False)
                blackboard.put(f"worker/{worker_id}", output, worker_id)
                return worker_id, output

            # Fallback: direct single-agent response
            worker = agents.get(worker_id)
            if not worker:
                return worker_id, f"Error: agent {worker_id} not found"
            msg = AgentMessage(
                type=MessageType.TASK,
                from_agent=self.manager_id,
                to_agent=worker_id,
                team_id=team_id,
                payload={"prompt": task_desc},
            )
            resp = await worker.handle_message(msg)
            result = resp.payload.get("content", "")
            blackboard.put(f"worker/{worker_id}", result, worker_id)
            return worker_id, result

        worker_tasks = [
            run_worker(wid, subtasks.get(wid, task_prompt))
            for wid in self.worker_ids if wid in agents or wid in self.worker_sub_agents
        ]
        worker_results = dict(await asyncio.gather(*worker_tasks))

        # Step 3: Manager synthesizes
        synth = await self._synthesize(manager, task_prompt, worker_results, team_id)

        return {
            "status": "completed",
            "manager": self.manager_id,
            "worker_results": worker_results,
            "synthesis": synth,
            "blackboard": blackboard.snapshot(),
        }

    async def _synthesize(
        self, manager: LLMAgent, goal: str,
        results: dict[str, str], team_id: str,
    ) -> str:
        synthesis_prompt = (
            f"Original goal: {goal}\n\nWorker outputs:\n"
            f"{json.dumps(results, indent=2)}\n\n"
            "Synthesize these results into a final answer. Be comprehensive."
        )
        synth_msg = AgentMessage(
            type=MessageType.TASK,
            from_agent="system",
            to_agent=self.manager_id,
            team_id=team_id,
            payload={"prompt": synthesis_prompt},
        )
        synth_resp = await manager.handle_message(synth_msg)
        return synth_resp.payload.get("content", "")


class MultiAgentOrchestrator:
    """Coordinates a team of agents using a pluggable conversation strategy."""

    def __init__(self, bus: Optional[MessageBus] = None):
        self.bus = bus or MessageBus()

    async def run_team(
        self,
        team_id: str,
        agents: dict[str, LLMAgent],
        strategy: ConversationStrategy,
        initial_task: dict,
        blackboard: Optional[SharedBlackboard] = None,
    ) -> dict:
        """Execute a multi-agent conversation."""
        bb = blackboard or SharedBlackboard(team_id)
        started_at = time.time()

        # Setup all agents
        for agent in agents.values():
            await agent.setup()

        try:
            result = await asyncio.wait_for(
                strategy.execute(agents, bb, self.bus, initial_task),
                timeout=strategy.timeout,
            )
        except asyncio.TimeoutError:
            result = {"status": "timeout", "error": f"Team {team_id} timed out"}
        except Exception as e:
            logger.exception(f"Team {team_id} failed: {e}")
            result = {"status": "failed", "error": str(e)}

        result["team_id"] = team_id
        result["duration"] = time.time() - started_at

        # Cleanup all agents
        for agent in agents.values():
            await agent.cleanup()

        return result
