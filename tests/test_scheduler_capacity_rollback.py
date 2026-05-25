"""Tests for enqueue capacity rollback — bounty #3662."""

import asyncio

import pytest

from src.orchestrator.scheduler import TaskScheduler


class TestCapacityTracking:
    def test_set_capacity_stores_max(self):
        s = TaskScheduler()
        s.set_capacity("default", 10)
        assert s.get_capacity("default") == 10

    def test_get_capacity_unknown_returns_none(self):
        s = TaskScheduler()
        assert s.get_capacity("nonexistent") is None

    def test_get_usage_unknown_returns_zero(self):
        s = TaskScheduler()
        assert s.get_usage("unknown") == 0

    def test_release_capacity_decrements_usage(self):
        s = TaskScheduler()
        s.set_capacity("default", 10)
        s._usage["default"] = 5
        released = s.release_capacity("default", 2)
        assert released == 2
        assert s.get_usage("default") == 3

    def test_release_capacity_does_not_go_negative(self):
        s = TaskScheduler()
        s.set_capacity("default", 10)
        s._usage["default"] = 1
        released = s.release_capacity("default", 5)
        assert released == 1
        assert s.get_usage("default") == 0


class TestCapacityLimit:
    def test_enqueue_within_capacity_succeeds(self):
        s = TaskScheduler()
        s.set_capacity("default", 3)
        for i in range(3):
            tid = s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
            assert tid is not None

    def test_enqueue_at_capacity_raises(self):
        s = TaskScheduler()
        s.set_capacity("default", 2)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        with pytest.raises(RuntimeError, match="at capacity"):
            s.enqueue({"type": "test", "target_agent": "a"}, queue="default")

    def test_enqueue_without_capacity_set_unlimited(self):
        s = TaskScheduler()
        for _ in range(100):
            tid = s.enqueue({"type": "test", "target_agent": "a"})
            assert tid is not None

    def test_complete_releases_capacity(self):
        s = TaskScheduler()
        s.set_capacity("default", 2)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        with pytest.raises(RuntimeError):
            s.enqueue({"type": "test", "target_agent": "a"}, queue="default")

        task = asyncio.run(s.dequeue())
        s.complete(task["id"])
        tid = s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        assert tid is not None

    def test_fail_max_retries_releases_capacity(self):
        s = TaskScheduler(max_retries=1)
        s.set_capacity("default", 1)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        task = asyncio.run(s.dequeue())
        s.fail(task["id"])
        tid = s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        assert tid is not None

    def test_fail_with_retries_preserves_capacity(self):
        s = TaskScheduler(max_retries=3)
        s.set_capacity("default", 1)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        task = asyncio.run(s.dequeue())
        s.fail(task["id"])
        with pytest.raises(RuntimeError):
            s.enqueue({"type": "test", "target_agent": "a"}, queue="default")

    def test_multiple_queues_independent_capacity(self):
        s = TaskScheduler()
        s.set_capacity("q1", 1)
        s.set_capacity("q2", 1)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="q1")
        s.enqueue({"type": "test", "target_agent": "a"}, queue="q2")
        with pytest.raises(RuntimeError):
            s.enqueue({"type": "test", "target_agent": "a"}, queue="q1")
        with pytest.raises(RuntimeError):
            s.enqueue({"type": "test", "target_agent": "a"}, queue="q2")
