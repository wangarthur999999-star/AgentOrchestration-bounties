"""Tests for TaskScheduler health gate — defers runs during dependency outages."""

import pytest

from src.orchestrator.scheduler import TaskScheduler


@pytest.fixture
def scheduler():
    return TaskScheduler()


class TestHealthGateBasics:
    def test_initially_healthy(self, scheduler):
        assert scheduler.is_healthy()

    def test_mark_unhealthy(self, scheduler):
        scheduler.set_health("db", False)
        assert not scheduler.is_healthy()

    def test_mark_healthy_restored(self, scheduler):
        scheduler.set_health("db", False)
        scheduler.set_health("db", True)
        assert scheduler.is_healthy()

    def test_multiple_dependencies_all_must_be_healthy(self, scheduler):
        scheduler.set_health("db", False)
        scheduler.set_health("redis", True)
        assert not scheduler.is_healthy()

    def test_all_recovered(self, scheduler):
        scheduler.set_health("db", False)
        scheduler.set_health("api", False)
        scheduler.set_health("db", True)
        assert not scheduler.is_healthy()
        scheduler.set_health("api", True)
        assert scheduler.is_healthy()


class TestHealthGateDeferral:
    def test_dequeue_returns_none_when_unhealthy(self, scheduler):
        scheduler.enqueue({"name": "test-task"})
        scheduler.set_health("db", False)
        assert scheduler.try_dequeue() is None

    def test_dequeue_returns_task_when_healthy(self, scheduler):
        scheduler.enqueue({"name": "test-task"})
        task = scheduler.try_dequeue()
        assert task is not None
        assert task["name"] == "test-task"

    def test_dequeue_resumes_after_health_restored(self, scheduler):
        scheduler.enqueue({"name": "task-a"})
        scheduler.set_health("api", False)
        assert scheduler.try_dequeue() is None
        scheduler.set_health("api", True)
        task = scheduler.try_dequeue()
        assert task["name"] == "task-a"

    def test_tasks_preserved_in_queue_during_outage(self, scheduler):
        scheduler.enqueue({"name": "task-1"})
        scheduler.enqueue({"name": "task-2"})
        scheduler.set_health("redis", False)

        assert scheduler.try_dequeue() is None
        assert scheduler.try_dequeue() is None
        assert scheduler.queue_size() == 2

    def test_tasks_dequeued_after_recovery(self, scheduler):
        scheduler.enqueue({"name": "delayed"})
        scheduler.set_health("service", False)
        scheduler.try_dequeue()
        scheduler.set_health("service", True)
        task = scheduler.try_dequeue()
        assert task["name"] == "delayed"


class TestHealthGateEdgeCases:
    def test_enqueue_not_affected_by_health(self, scheduler):
        scheduler.set_health("db", False)
        tid = scheduler.enqueue({"name": "critical"})
        assert tid is not None
        assert scheduler.queue_size() == 1

    def test_idempotent_unhealthy_marking(self, scheduler):
        scheduler.set_health("db", False)
        scheduler.set_health("db", False)
        assert not scheduler.is_healthy()

    def test_idempotent_healthy_marking(self, scheduler):
        scheduler.set_health("db", True)
        scheduler.set_health("db", True)
        assert scheduler.is_healthy()

    def test_unknown_dependency_healthy_by_default(self, scheduler):
        scheduler.set_health("unknown_service", True)
        assert scheduler.is_healthy()

    def test_complete_still_works_during_outage(self, scheduler):
        scheduler.enqueue({"name": "inflight"})
        task = scheduler.try_dequeue()
        scheduler.set_health("db", False)
        assert scheduler.complete(task["id"])

    def test_fail_retry_works_during_outage(self, scheduler):
        scheduler.enqueue({"name": "retry-me"})
        task = scheduler.try_dequeue()
        scheduler.set_health("db", False)
        assert scheduler.fail(task["id"])  # Retries still enqueue
