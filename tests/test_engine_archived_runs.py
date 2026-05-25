"""Tests for engine archived-run rejection — bounty #3880."""

import pytest

from src.agent.registry import AgentRegistry, AgentStatus
from src.orchestrator.engine import OrchestrationEngine


@pytest.fixture
def engine():
    return OrchestrationEngine()


@pytest.fixture
def registered_agent(engine):
    agent_id = engine.registry.register("test-agent", "worker.default")
    return agent_id


class TestArchivedStatusExists:
    def test_archived_in_enum(self):
        assert hasattr(AgentStatus, "ARCHIVED")
        assert AgentStatus.ARCHIVED.value == "archived"

    def test_archived_is_valid_status(self):
        agent_id = AgentRegistry().register("a", "worker.default")
        reg = AgentRegistry()
        reg._agents = AgentRegistry()._agents  # not needed
        registry = AgentRegistry()
        aid = registry.register("archived-agent", "worker.default")
        assert registry.update_status(aid, AgentStatus.ARCHIVED)
        assert registry.get(aid)["status"] == "archived"


class TestEngineRejectsArchivedRuns:
    def test_task_rejected_for_archived_agent(self, engine, registered_agent):
        engine.registry.update_status(registered_agent, AgentStatus.ARCHIVED)
        task = {"id": "task-1", "target_agent": registered_agent}

        # Direct call _execute_task (synchronous path for testing)
        import asyncio
        asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "archived"

    def test_task_still_processed_for_running_agent(self, engine, registered_agent):
        task = {"id": "task-2", "target_agent": registered_agent}

        import asyncio
        asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "paused"

    def test_task_still_processed_for_pending_agent(self, engine, registered_agent):
        task = {"id": "task-3", "target_agent": registered_agent}

        import asyncio
        asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "paused"


class TestEngineRejectsMissingAgents:
    def test_task_rejected_for_nonexistent_agent(self, engine):
        task = {"id": "task-4", "target_agent": "nonexistent-id"}

        import asyncio
        asyncio.run(engine._execute_task(task))

        # Should not raise, just log and return


class TestArchivedPreservesStatus:
    def test_archived_agent_stays_archived(self, engine, registered_agent):
        engine.registry.update_status(registered_agent, AgentStatus.ARCHIVED)

        import asyncio
        for i in range(3):
            task = {"id": f"task-{i}", "target_agent": registered_agent}
            asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "archived"

    def test_non_archived_agents_unaffected(self, engine):
        a1 = engine.registry.register("agent-1", "worker.a")
        a2 = engine.registry.register("agent-2", "worker.b")
        engine.registry.update_status(a2, AgentStatus.ARCHIVED)

        import asyncio
        task_a1 = {"id": "task-a1", "target_agent": a1}
        task_a2 = {"id": "task-a2", "target_agent": a2}

        asyncio.run(engine._execute_task(task_a1))
        asyncio.run(engine._execute_task(task_a2))

        assert engine.registry.get(a1)["status"] == "paused"
        assert engine.registry.get(a2)["status"] == "archived"


class TestArchivedEdgeCases:
    def test_terminated_agent_still_processed(self, engine, registered_agent):
        engine.registry.update_status(registered_agent, AgentStatus.TERMINATED)
        task = {"id": "task-t", "target_agent": registered_agent}

        import asyncio
        asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "paused"

    def test_failed_agent_still_processed(self, engine, registered_agent):
        engine.registry.update_status(registered_agent, AgentStatus.FAILED)
        task = {"id": "task-f", "target_agent": registered_agent}

        import asyncio
        asyncio.run(engine._execute_task(task))

        agent = engine.registry.get(registered_agent)
        assert agent["status"] == "paused"

    def test_archive_then_reregister(self, engine, registered_agent):
        engine.registry.update_status(registered_agent, AgentStatus.ARCHIVED)

        new_id = engine.registry.register("test-agent-v2", "worker.default")
        task = {"id": "task-new", "target_agent": new_id}

        import asyncio
        asyncio.run(engine._execute_task(task))

        assert engine.registry.get(registered_agent)["status"] == "archived"
        assert engine.registry.get(new_id)["status"] == "paused"
