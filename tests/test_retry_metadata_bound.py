"""Tests for bounded retry metadata in TaskScheduler."""

import pytest

from src.orchestrator.scheduler import TaskScheduler


@pytest.fixture
def scheduler():
    return TaskScheduler()


class TestRetryCounterPreserved:
    def test_new_task_starts_at_zero(self, scheduler):
        tid = scheduler.enqueue({"name": "task"})
        task = scheduler.try_dequeue()
        assert task["retries"] == 0

    def test_fail_increments_retry(self, scheduler):
        scheduler.enqueue({"name": "task"})
        task = scheduler.try_dequeue()
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        assert retried["retries"] == 1

    def test_retry_not_reset_by_enqueue(self, scheduler):
        scheduler.enqueue({"name": "task"})
        task = scheduler.try_dequeue()
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        assert retried["retries"] == 1

    def test_retries_accumulate_across_failures(self, scheduler):
        scheduler.enqueue({"name": "flaky"})
        task = scheduler.try_dequeue()
        assert task["retries"] == 0

        scheduler.fail(task["id"])
        task = scheduler.try_dequeue()
        assert task["retries"] == 1

        scheduler.fail(task["id"])
        task = scheduler.try_dequeue()
        assert task["retries"] == 2


class TestMaxRetriesEnforced:
    def test_task_dropped_after_max_retries(self, scheduler):
        scheduler._max_retries = 3
        scheduler.enqueue({"name": "doomed"})
        task = scheduler.try_dequeue()

        result1 = scheduler.fail(task["id"])  # retries: 0→1
        assert result1 is True
        task = scheduler.try_dequeue()

        result2 = scheduler.fail(task["id"])  # retries: 1→2
        assert result2 is True
        task = scheduler.try_dequeue()

        result3 = scheduler.fail(task["id"])  # retries: 2→3, now >= max
        assert result3 is False
        assert scheduler.try_dequeue() is None

    def test_retry_count_does_not_exceed_max(self, scheduler):
        scheduler._max_retries = 2
        scheduler.enqueue({"name": "x"})
        task = scheduler.try_dequeue()
        scheduler.fail(task["id"])  # 0→1
        task = scheduler.try_dequeue()
        assert task["retries"] == 1
        scheduler.fail(task["id"])  # 1→2, dropped
        assert scheduler.try_dequeue() is None


class TestMetadataBounded:
    def test_retry_only_adds_retries_field(self, scheduler):
        scheduler.enqueue({"name": "lean"})
        task = scheduler.try_dequeue()
        keys_before = set(task.keys())
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        new_keys = set(retried.keys()) - keys_before
        assert not new_keys

    def test_no_duplicate_id_growth(self, scheduler):
        scheduler.enqueue({"name": "task"})
        task = scheduler.try_dequeue()
        original_id = task["id"]
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        assert retried["id"] != original_id
        assert isinstance(retried["id"], str)

    def test_enqueued_at_updated_on_retry(self, scheduler):
        import time
        scheduler.enqueue({"name": "task"})
        task = scheduler.try_dequeue()
        original_ts = task["enqueued_at"]
        time.sleep(0.01)
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        assert retried["enqueued_at"] > original_ts


class TestRetryEdgeCases:
    def test_custom_max_retries(self, scheduler):
        scheduler._max_retries = 5
        scheduler.enqueue({"name": "test"})
        task = scheduler.try_dequeue()
        for i in range(4):
            assert scheduler.fail(task["id"])
            task = scheduler.try_dequeue()
            assert task["retries"] == i + 1
        assert not scheduler.fail(task["id"])

    def test_priority_preserved_on_retry(self, scheduler):
        scheduler.enqueue({"name": "p1", "priority": 5}, priority=5)
        task = scheduler.try_dequeue()
        scheduler.fail(task["id"])
        retried = scheduler.try_dequeue()
        assert retried.get("priority") == 5

    def test_complete_clears_in_flight(self, scheduler):
        scheduler.enqueue({"name": "ok"})
        task = scheduler.try_dequeue()
        assert scheduler.complete(task["id"])
        assert scheduler.try_dequeue() is None

    def test_fail_nonexistent_task(self, scheduler):
        assert scheduler.fail("nonexistent-id") is False
