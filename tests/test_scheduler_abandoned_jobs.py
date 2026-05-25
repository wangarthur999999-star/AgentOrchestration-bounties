"""Tests for abandoned job reclamation — bounty #3729."""

import asyncio
import time

from src.orchestrator.scheduler import TaskScheduler


class TestAbandonedJobReclamation:
    def test_reclaim_abandoned_returns_empty_when_nothing_abandoned(self):
        s = TaskScheduler()
        result = s.reclaim_abandoned(ttl=0.1)
        assert result == {"abandoned": 0, "re_enqueued": 0}

    def test_reclaim_abandoned_detects_expired_reservation(self):
        s = TaskScheduler(reservation_ttl=0.01)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        asyncio.run(s.dequeue())
        time.sleep(0.05)
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 1
        assert result["re_enqueued"] == 1

    def test_reclaim_abandoned_ignores_active_reservation(self):
        s = TaskScheduler(reservation_ttl=10.0)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        asyncio.run(s.dequeue())
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 0

    def test_reclaim_abandoned_re_enqueues_for_retry(self):
        s = TaskScheduler(reservation_ttl=0.01)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        asyncio.run(s.dequeue())
        time.sleep(0.05)
        s.reclaim_abandoned()
        task = asyncio.run(s.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_completed_task_not_reclaimed(self):
        s = TaskScheduler(reservation_ttl=0.01)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        task = asyncio.run(s.dequeue())
        s.complete(task["id"])
        time.sleep(0.05)
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 0

    def test_failed_task_not_reclaimed(self):
        s = TaskScheduler(reservation_ttl=0.01)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        task = asyncio.run(s.dequeue())
        s.fail(task["id"])
        time.sleep(0.05)
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 0

    def test_default_reservation_ttl(self):
        s = TaskScheduler()
        assert s._reservation_ttl == 300.0

    def test_set_reservation_ttl(self):
        s = TaskScheduler()
        s.set_reservation_ttl(60.0)
        assert s._reservation_ttl == 60.0

    def test_reclaim_uses_default_ttl_when_not_specified(self):
        s = TaskScheduler(reservation_ttl=0.01)
        s.enqueue({"type": "test", "target_agent": "a"}, queue="default")
        asyncio.run(s.dequeue())
        time.sleep(0.05)
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 1

    def test_reclaim_multiple_abandoned(self):
        s = TaskScheduler(reservation_ttl=0.01)
        for i in range(3):
            s.enqueue({"type": "test", "target_agent": "a", "idx": i}, queue="default")
            asyncio.run(s.dequeue())
        time.sleep(0.05)
        result = s.reclaim_abandoned()
        assert result["abandoned"] == 3
        assert result["re_enqueued"] == 3
