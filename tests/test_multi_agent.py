"""Tests for multi-agent conversation strategies."""

import asyncio

import pytest

from src.orchestrator.memory import SharedBlackboard
from src.orchestrator.multi_agent import (
    DebateStrategy,
    GroupChatStrategy,
    ManagerWorkerStrategy,
    MultiAgentOrchestrator,
    RoundRobinStrategy,
)
from src.orchestrator.protocol import AgentMessage, MessageBus, MessageType

# ---------------------------------------------------------------------------
# Mock agent that echoes or returns predefined responses
# ---------------------------------------------------------------------------


class MockLLMAgent:
    """Simulates an LLMAgent for testing without API calls."""

    def __init__(self, agent_id: str, name: str, response: str = ""):
        self.agent_id = agent_id
        self.name = name
        self._response = response or f"Response from {name}"
        self.outbox: list = []
        self.setup_called = False
        self.cleanup_called = False

    async def setup(self):
        self.setup_called = True

    async def cleanup(self):
        self.cleanup_called = True

    async def handle_message(self, message: AgentMessage) -> AgentMessage:
        prompt = message.payload.get("prompt", "")
        response = AgentMessage(
            type=MessageType.RESPONSE,
            from_agent=self.agent_id,
            to_agent=message.from_agent,
            team_id=message.team_id,
            payload={"content": f"{self._response} | received: {prompt[:50]}"},
            reply_to=message.id,
        )
        self.outbox.append(response)
        return response


# ---------------------------------------------------------------------------
# RoundRobinStrategy
# ---------------------------------------------------------------------------


class TestRoundRobinStrategy:
    @pytest.mark.asyncio
    async def test_two_agent_round_robin(self):
        agent_a = MockLLMAgent("a", "Agent A", "output A")
        agent_b = MockLLMAgent("b", "Agent B", "output B")
        agents = {"a": agent_a, "b": agent_b}

        bb = SharedBlackboard("team-rr")
        bus = MessageBus()
        strategy = RoundRobinStrategy(agent_order=["a", "b"], max_rounds=1)

        result = await strategy.execute(agents, bb, bus, {"prompt": "Test task"})

        assert result["status"] == "completed"
        assert "a" in result["blackboard"]
        assert "b" in result["blackboard"]
        assert agent_a.setup_called is False  # setup called by orchestrator, not strategy

    @pytest.mark.asyncio
    async def test_round_robin_skips_missing_agents(self):
        agent_a = MockLLMAgent("a", "Agent A", "output A")
        agents = {"a": agent_a}

        bb = SharedBlackboard("team-rr2")
        bus = MessageBus()
        strategy = RoundRobinStrategy(agent_order=["a", "nonexistent"], max_rounds=1)

        result = await strategy.execute(agents, bb, bus, {"prompt": "test"})
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_multiple_rounds(self):
        agent_a = MockLLMAgent("a", "Agent A", "round output")
        agents = {"a": agent_a}

        bb = SharedBlackboard("team-mr")
        bus = MessageBus()
        strategy = RoundRobinStrategy(agent_order=["a"], max_rounds=3)

        result = await strategy.execute(agents, bb, bus, {"prompt": "multi-round"})
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# GroupChatStrategy
# ---------------------------------------------------------------------------


class TestGroupChatStrategy:
    @pytest.mark.asyncio
    async def test_group_chat_basic(self):
        agent_a = MockLLMAgent("a", "Agent A", "###TERMINATE###")
        agent_b = MockLLMAgent("b", "Agent B", "group chat output")
        agents = {"a": agent_a, "b": agent_b}

        bb = SharedBlackboard("team-gc")
        bus = MessageBus()
        strategy = GroupChatStrategy(max_rounds=3)

        result = await strategy.execute(agents, bb, bus, {"prompt": "Discuss this"})

        assert result["status"] == "completed"
        assert len(result["history"]) > 0


# ---------------------------------------------------------------------------
# DebateStrategy
# ---------------------------------------------------------------------------


class TestDebateStrategy:
    @pytest.mark.asyncio
    async def test_debate_with_two_agents(self):
        agent_a = MockLLMAgent("a", "Pro", "I support this proposal")
        agent_b = MockLLMAgent("b", "Con", "I oppose this proposal")
        agents = {"a": agent_a, "b": agent_b}

        bb = SharedBlackboard("team-debate")
        bus = MessageBus()
        strategy = DebateStrategy(debate_topic="Should we use Rust?", max_rounds=2)

        result = await strategy.execute(agents, bb, bus, {"prompt": "Debate topic"})

        assert result["status"] == "completed"
        assert "positions" in result
        assert "votes" in result
        assert "winner" in result

    @pytest.mark.asyncio
    async def test_debate_positions_stored(self):
        agent_a = MockLLMAgent("a", "Agent A", "Position A: agree")
        agent_b = MockLLMAgent("b", "Agent B", "Position B: disagree")
        agents = {"a": agent_a, "b": agent_b}

        bb = SharedBlackboard("team-db2")
        bus = MessageBus()
        strategy = DebateStrategy(debate_topic="Tabs vs spaces", max_rounds=1)

        result = await strategy.execute(agents, bb, bus, {"prompt": "Debate"})

        positions = result.get("positions", {})
        assert len(positions) >= 2


# ---------------------------------------------------------------------------
# ManagerWorkerStrategy
# ---------------------------------------------------------------------------


class TestManagerWorkerStrategy:
    @pytest.mark.asyncio
    async def test_manager_worker_basic(self):
        manager = MockLLMAgent(
            "mgr", "Manager",
            '{"subtasks": [{"worker": "w1", "task": "Analyze code"}, '
            '{"worker": "w2", "task": "Write tests"}]}',
        )
        worker1 = MockLLMAgent("w1", "Worker 1", "Analysis complete")
        worker2 = MockLLMAgent("w2", "Worker 2", "Tests generated")
        agents = {"mgr": manager, "w1": worker1, "w2": worker2}

        bb = SharedBlackboard("team-mw")
        bus = MessageBus()
        strategy = ManagerWorkerStrategy(
            manager_agent_id="mgr",
            worker_agent_ids=["w1", "w2"],
        )

        result = await strategy.execute(agents, bb, bus, {"prompt": "Process this"})

        assert result["status"] == "completed"
        assert result["manager"] == "mgr"
        assert "worker_results" in result
        assert "synthesis" in result

    @pytest.mark.asyncio
    async def test_manager_not_found(self):
        agents = {"w1": MockLLMAgent("w1", "Worker", "output")}
        bb = SharedBlackboard("team-mw2")
        bus = MessageBus()
        strategy = ManagerWorkerStrategy(
            manager_agent_id="nonexistent",
            worker_agent_ids=["w1"],
        )

        result = await strategy.execute(agents, bb, bus, {"prompt": "test"})
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_workers_run_in_parallel(self):
        import time

        manager = MockLLMAgent(
            "mgr", "Manager",
            '{"subtasks": [{"worker": "w1", "task": "task1"}, '
            '{"worker": "w2", "task": "task2"}]}',
        )

        class SlowMockAgent(MockLLMAgent):
            async def handle_message(self, message):
                await asyncio.sleep(0.05)
                return await super().handle_message(message)

        worker1 = SlowMockAgent("w1", "Worker 1", "done1")
        worker2 = SlowMockAgent("w2", "Worker 2", "done2")
        agents = {"mgr": manager, "w1": worker1, "w2": worker2}

        bb = SharedBlackboard("team-parallel")
        bus = MessageBus()
        strategy = ManagerWorkerStrategy("mgr", ["w1", "w2"])

        start = time.time()
        result = await strategy.execute(agents, bb, bus, {"prompt": "test parallel"})
        elapsed = time.time() - start

        # Parallel execution: both sleep 0.05s, should finish in ~0.05s, not ~0.1s
        assert result["status"] == "completed"
        assert elapsed < 0.15  # generous buffer for CI


# ---------------------------------------------------------------------------
# MultiAgentOrchestrator
# ---------------------------------------------------------------------------


class TestMultiAgentOrchestrator:
    @pytest.mark.asyncio
    async def test_run_team_sets_up_and_cleans_up_agents(self):
        agent_a = MockLLMAgent("a", "A", "output")
        agent_b = MockLLMAgent("b", "B", "output")
        agents = {"a": agent_a, "b": agent_b}

        orch = MultiAgentOrchestrator()
        strategy = RoundRobinStrategy(agent_order=["a", "b"], max_rounds=1)
        result = await orch.run_team("team-1", agents, strategy, {"prompt": "hi"})

        assert result["status"] == "completed"
        assert result["team_id"] == "team-1"
        assert "duration" in result
        assert agent_a.setup_called
        assert agent_a.cleanup_called
        assert agent_b.setup_called
        assert agent_b.cleanup_called

    @pytest.mark.asyncio
    async def test_run_team_custom_blackboard(self):
        agent = MockLLMAgent("a", "A", "output")
        bb = SharedBlackboard("custom-bb")
        bb.put("preloaded", "data", "system")

        orch = MultiAgentOrchestrator()
        strategy = RoundRobinStrategy(agent_order=["a"], max_rounds=1)
        result = await orch.run_team(
            "team-custom", {"a": agent}, strategy,
            {"prompt": "test"}, blackboard=bb,
        )

        assert result["status"] == "completed"
