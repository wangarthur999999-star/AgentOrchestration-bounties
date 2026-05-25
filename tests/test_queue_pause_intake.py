"""Tests for queue intake pause — bounty #3989."""

import pytest

from src.orchestrator.scheduler import TaskScheduler


@pytest.fixture
def scheduler():
    return TaskScheduler()


class TestPauseIntake:
    def test_pause_stops_dequeue(self, scheduler):
        scheduler.enqueue({"name": "task1"})
        scheduler.pause_intake("default", "schema migration")
        assert scheduler.intake_status() == {"default": "schema migration"}

    def test_dequeue_returns_none_when_paused(self, scheduler):
        scheduler.enqueue({"name": "task1"})
        scheduler.pause_intake("default", "maintenance")

        import asyncio
        result = asyncio.run(scheduler.dequeue("default", timeout=0.1))
        assert result is None

    def test_resume_restores_dequeue(self, scheduler):
        scheduler.enqueue({"name": "task1"})
        scheduler.pause_intake("default", "schema changes")
        scheduler.resume_intake("default")

        import asyncio
        result = asyncio.run(scheduler.dequeue("default", timeout=0.1))
        assert result is not None
        assert result["name"] == "task1"

    def test_pause_with_reason(self, scheduler):
        scheduler.pause_intake("api", "DB migration 2024-01")
        assert scheduler.intake_status()["api"] == "DB migration 2024-01"


class TestResumeIntake:
    def test_resume_returns_true_when_was_paused(self, scheduler):
        scheduler.pause_intake("default", "migration")
        assert scheduler.resume_intake("default") is True

    def test_resume_returns_false_when_not_paused(self, scheduler):
        assert scheduler.resume_intake("default") is False

    def test_resume_clears_status(self, scheduler):
        scheduler.pause_intake("default", "migration")
        scheduler.resume_intake("default")
        assert scheduler.intake_status() == {}

    def test_resume_idempotent(self, scheduler):
        scheduler.pause_intake("default", "migration")
        scheduler.resume_intake("default")
        assert scheduler.resume_intake("default") is False


class TestPauseEdgeCases:
    def test_pause_only_affects_specified_queue(self, scheduler):
        scheduler.enqueue({"name": "t1"}, queue="default")
        scheduler.enqueue({"name": "t2"}, queue="high")
        scheduler.pause_intake("default", "migration")

        import asyncio
        r_default = asyncio.run(scheduler.dequeue("default", timeout=0.1))
        r_high = asyncio.run(scheduler.dequeue("high", timeout=0.1))

        assert r_default is None
        assert r_high is not None
        assert r_high["name"] == "t2"

    def test_multiple_queues_paused_independently(self, scheduler):
        scheduler.pause_intake("q1", "reason 1")
        scheduler.pause_intake("q2", "reason 2")

        status = scheduler.intake_status()
        assert status == {"q1": "reason 1", "q2": "reason 2"}

    def test_enqueue_still_works_during_pause(self, scheduler):
        scheduler.pause_intake("default", "migration")
        task_id = scheduler.enqueue({"name": "later"})
        assert task_id is not None
        assert scheduler.queue_size("default") == 1

    def test_complete_still_works_during_pause(self, scheduler):
        scheduler.enqueue({"name": "t1"})
        import asyncio
        task = asyncio.run(scheduler.dequeue("default", timeout=0.1))
        scheduler.pause_intake("default", "migration")
        assert scheduler.complete(task["id"]) is True

    def test_fail_still_works_during_pause(self, scheduler):
        scheduler.enqueue({"name": "t1"})
        import asyncio
        task = asyncio.run(scheduler.dequeue("default", timeout=0.1))
        scheduler.pause_intake("default", "migration")
        assert scheduler.fail(task["id"]) is True  # 1 retry < 3 max_retries, so re-queued

    def test_pause_reason_overwrites(self, scheduler):
        scheduler.pause_intake("default", "first pause")
        scheduler.pause_intake("default", "second pause")
        assert scheduler.intake_status()["default"] == "second pause"


class TestQueueSize:
    def test_queue_size_reports_correctly(self, scheduler):
        scheduler.enqueue({"name": "t1"})
        scheduler.enqueue({"name": "t2"})
        assert scheduler.queue_size("default") == 2

    def test_queue_size_zero_unknown_queue(self, scheduler):
        assert scheduler.queue_size("nonexistent") == 0
