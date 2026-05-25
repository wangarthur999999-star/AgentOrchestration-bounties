"""Tests for executor orphaned artifact cleanup — bounty #3911."""

import asyncio
import time

import pytest

from src.agent.executor import AgentExecutor


async def _noop_handler(agent_id: str, task: dict) -> dict:
    return {"status": "ok"}


async def _failing_handler(agent_id: str, task: dict) -> dict:
    raise RuntimeError("simulated failure")


class TestResultStorage:
    def test_result_stored_after_success(self):
        executor = AgentExecutor()
        eid = asyncio.run(executor.execute("agent-1", {"id": "task-1"}, _noop_handler))
        result = executor.get_result(eid)
        assert result is not None
        assert result["result"]["status"] == "ok"
        assert result["agent_id"] == "agent-1"

    def test_error_stored_on_failure(self):
        executor = AgentExecutor()
        eid = asyncio.run(executor.execute("agent-1", {"id": "task-2"}, _failing_handler))
        result = executor.get_result(eid)
        assert result is not None
        assert "error" in result

    def test_result_count_increments(self):
        executor = AgentExecutor()
        assert executor.result_count() == 0
        asyncio.run(executor.execute("agent-1", {"id": "task-1"}, _noop_handler))
        assert executor.result_count() == 1
        asyncio.run(executor.execute("agent-2", {"id": "task-2"}, _noop_handler))
        assert executor.result_count() == 2

    def test_get_result_nonexistent(self):
        executor = AgentExecutor()
        assert executor.get_result("nonexistent") is None


class TestResultEviction:
    def test_oldest_evicted_at_max_capacity(self):
        executor = AgentExecutor(max_results=3)
        eid1 = asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        time.sleep(0.01)
        eid2 = asyncio.run(executor.execute("a", {"id": "2"}, _noop_handler))
        time.sleep(0.01)
        eid3 = asyncio.run(executor.execute("a", {"id": "3"}, _noop_handler))
        assert executor.result_count() == 3

        eid4 = asyncio.run(executor.execute("a", {"id": "4"}, _noop_handler))
        assert executor.result_count() == 3
        assert executor.get_result(eid1) is None
        assert executor.get_result(eid2) is not None
        assert executor.get_result(eid3) is not None
        assert executor.get_result(eid4) is not None

    def test_eviction_only_when_over_capacity(self):
        executor = AgentExecutor(max_results=100)
        for i in range(50):
            asyncio.run(executor.execute("a", {"id": str(i)}, _noop_handler))
        assert executor.result_count() == 50

    def test_empty_eviction_no_error(self):
        executor = AgentExecutor(max_results=1)
        executor._evict_oldest()
        assert executor.result_count() == 0


class TestOrphanCleanup:
    def test_cleanup_removes_expired_results(self):
        executor = AgentExecutor(grace_period=0.01)
        asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        assert executor.result_count() == 1

        time.sleep(0.02)
        result = executor.cleanup_orphaned()
        assert result["orphaned_count"] == 1
        assert result["deleted_bytes"] > 0
        assert executor.result_count() == 0

    def test_cleanup_keeps_recent_results(self):
        executor = AgentExecutor(grace_period=3600.0)
        asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        assert executor.result_count() == 1

        result = executor.cleanup_orphaned()
        assert result["orphaned_count"] == 0
        assert executor.result_count() == 1

    def test_cleanup_empty_executor(self):
        executor = AgentExecutor()
        result = executor.cleanup_orphaned()
        assert result == {"orphaned_count": 0, "deleted_bytes": 0}

    def test_cleanup_partial_expiry(self):
        executor = AgentExecutor(grace_period=0.1)
        eid1 = asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        time.sleep(0.06)
        eid2 = asyncio.run(executor.execute("a", {"id": "2"}, _noop_handler))
        time.sleep(0.05)
        # eid1 ~0.11s old (expired), eid2 ~0.05s old (fresh)
        result = executor.cleanup_orphaned()
        assert result["orphaned_count"] == 1
        assert executor.get_result(eid1) is None
        assert executor.get_result(eid2) is not None

    def test_cleanup_deleted_bytes_positive(self):
        executor = AgentExecutor(grace_period=0.01)
        asyncio.run(executor.execute("a", {"id": "big"}, _noop_handler))
        time.sleep(0.02)
        result = executor.cleanup_orphaned()
        assert result["deleted_bytes"] > 0


class TestCancelCleanup:
    def test_cancel_completed_task_preserves_result(self):
        executor = AgentExecutor()
        eid = asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        assert executor.get_result(eid) is not None
        # Task already done — cancel returns False, result persists
        assert executor.cancel(eid) is False
        assert executor.get_result(eid) is not None

    def test_cancel_nonexistent_returns_false(self):
        executor = AgentExecutor()
        assert executor.cancel("nonexistent") is False

    def test_cancel_already_done_returns_false(self):
        executor = AgentExecutor()
        eid = asyncio.run(executor.execute("a", {"id": "1"}, _noop_handler))
        assert executor.cancel(eid) is False


class TestInitDefaults:
    def test_default_max_results(self):
        executor = AgentExecutor()
        assert executor.max_results == 1000

    def test_default_grace_period(self):
        executor = AgentExecutor()
        assert executor.grace_period == 3600.0

    def test_custom_values(self):
        executor = AgentExecutor(max_concurrent=3, max_results=50, grace_period=60.0)
        assert executor.max_concurrent == 3
        assert executor.max_results == 50
        assert executor.grace_period == 60.0
