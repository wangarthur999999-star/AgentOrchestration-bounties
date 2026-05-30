"""Tests for shared blackboard memory system."""

import asyncio
import time

import pytest

from src.orchestrator.memory import BlackboardEntry, SharedBlackboard


class TestBlackboardEntry:
    def test_creation(self):
        entry = BlackboardEntry(key="test", value={"a": 1}, created_by="agent-1")
        assert entry.key == "test"
        assert entry.value == {"a": 1}
        assert entry.version == 1
        assert entry.created_by == "agent-1"

    def test_version_increment_on_put(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "v1", "agent-1")
        bb.put("key", "v2", "agent-1")
        entry = bb.get_entry("key")
        assert entry.version == 2


class TestSharedBlackboard:
    def test_put_and_get(self):
        bb = SharedBlackboard("team-1")
        bb.put("result", {"score": 100}, "agent-a")
        assert bb.get("result") == {"score": 100}

    def test_get_nonexistent(self):
        bb = SharedBlackboard("team-1")
        assert bb.get("nonexistent") is None

    def test_get_entry_with_metadata(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "value", "agent-a")
        entry = bb.get_entry("key")
        assert entry is not None
        assert entry.created_by == "agent-a"
        assert entry.version == 1

    def test_get_all_with_prefix(self):
        bb = SharedBlackboard("team-1")
        bb.put("worker/a", "result-a", "a")
        bb.put("worker/b", "result-b", "b")
        bb.put("other", "other-value", "c")

        worker_results = bb.get_all("worker/")
        assert len(worker_results) == 2
        assert "worker/a" in worker_results

        all_results = bb.get_all()
        assert len(all_results) == 3

    def test_compare_and_swap_success(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "v1", "agent-a")
        assert bb.compare_and_swap("key", 1, "v2", "agent-b")
        assert bb.get("key") == "v2"

    def test_compare_and_swap_wrong_version(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "v1", "agent-a")
        assert not bb.compare_and_swap("key", 999, "v2", "agent-b")
        assert bb.get("key") == "v1"  # unchanged

    def test_compare_and_swap_nonexistent(self):
        bb = SharedBlackboard("team-1")
        assert not bb.compare_and_swap("key", 1, "v", "agent-a")

    @pytest.mark.asyncio
    async def test_watch(self):
        bb = SharedBlackboard("team-1")

        async def writer():
            await asyncio.sleep(0.05)
            bb.put("key", "hello", "agent-a")

        asyncio.create_task(writer())
        result = await bb.watch("key", timeout=1.0)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_watch_timeout(self):
        bb = SharedBlackboard("team-1")
        result = await bb.watch("never-set", timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_watch_existing_key_returns_immediately(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "value", "agent-a")
        result = await bb.watch("key")
        assert result == "value"

    def test_ttl_expiry(self):
        bb = SharedBlackboard("team-1")
        bb.put("ephemeral", "data", "agent-a", ttl=0.01)
        time.sleep(0.02)
        assert bb.get("ephemeral") is None

    def test_delete(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "value", "agent-a")
        assert bb.delete("key")
        assert bb.get("key") is None
        assert not bb.delete("nonexistent")

    def test_snapshot(self):
        bb = SharedBlackboard("team-1")
        bb.put("a", 1, "x")
        bb.put("b", 2, "y")
        snap = bb.snapshot()
        assert snap == {"a": 1, "b": 2}
        # Snapshot is a deep copy — mutations don't affect original
        snap["a"] = 999
        assert bb.get("a") == 1

    def test_clear(self):
        bb = SharedBlackboard("team-1")
        bb.put("a", 1, "x")
        bb.clear()
        assert len(bb) == 0
        assert bb.get("a") is None

    def test_contains(self):
        bb = SharedBlackboard("team-1")
        bb.put("key", "val", "agent")
        assert "key" in bb
        assert "nonexistent" not in bb

    def test_len(self):
        bb = SharedBlackboard("team-1")
        assert len(bb) == 0
        bb.put("a", 1, "x")
        bb.put("b", 2, "y")
        assert len(bb) == 2
