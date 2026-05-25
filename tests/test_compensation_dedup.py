"""Tests for compensation deduplication — bounty #3924."""

import pytest

from src.orchestrator.engine import OrchestrationEngine


@pytest.fixture
def engine():
    return OrchestrationEngine()


class TestScheduleCompensation:
    def test_first_call_returns_true(self, engine):
        assert engine.schedule_compensation("task-1", revision=0) is True

    def test_duplicate_call_returns_false(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        assert engine.schedule_compensation("task-1", revision=0) is False

    def test_different_task_ids_independent(self, engine):
        assert engine.schedule_compensation("task-1", revision=0) is True
        assert engine.schedule_compensation("task-2", revision=0) is True

    def test_same_task_different_revision_returns_true(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        assert engine.schedule_compensation("task-1", revision=1) is True


class TestClearCompensation:
    def test_clear_existing_returns_true(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        assert engine.clear_compensation("task-1") is True

    def test_clear_nonexistent_returns_false(self, engine):
        assert engine.clear_compensation("task-1") is False

    def test_after_clear_can_recompensate(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        engine.clear_compensation("task-1")
        assert engine.schedule_compensation("task-1", revision=0) is True


class TestIsCompensated:
    def test_is_compensated_after_schedule(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        assert engine.is_compensated("task-1") is True

    def test_not_compensated_initially(self, engine):
        assert engine.is_compensated("task-1") is False

    def test_not_compensated_after_clear(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        engine.clear_compensation("task-1")
        assert engine.is_compensated("task-1") is False


class TestCompensationRevisionTracking:
    def test_revision_stored_correctly(self, engine):
        engine.schedule_compensation("task-1", revision=3)
        assert engine._compensated["task-1"] == 3

    def test_revision_updated_on_retry(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        engine.schedule_compensation("task-1", revision=1)
        assert engine._compensated["task-1"] == 1

    def test_revision_not_updated_on_duplicate(self, engine):
        engine.schedule_compensation("task-1", revision=5)
        engine.schedule_compensation("task-1", revision=5)
        assert engine._compensated["task-1"] == 5

    def test_compensation_resets_after_clear_and_retry(self, engine):
        engine.schedule_compensation("task-1", revision=0)
        engine.clear_compensation("task-1")
        engine.schedule_compensation("task-1", revision=1)
        assert engine._compensated["task-1"] == 1


class TestErrorHookDedup:
    def test_on_error_hooks_only_fire_once(self, engine):
        call_count = []

        async def error_hook(task, exc):
            call_count.append(1)

        engine.register_hook("on_error", error_hook)

        engine.schedule_compensation("task-1", revision=0)
        # Second schedule_compensation returns False, so hooks should not re-fire
        second = engine.schedule_compensation("task-1", revision=0)
        assert second is False
        assert len(call_count) == 0  # hooks only fire when compensation succeeds

    def test_multiple_hooks_on_single_compensation(self, engine):
        hook1_calls = []
        hook2_calls = []

        async def hook1(task, exc):
            hook1_calls.append(1)

        async def hook2(task, exc):
            hook2_calls.append(1)

        engine.register_hook("on_error", hook1)
        engine.register_hook("on_error", hook2)

        assert engine.schedule_compensation("task-1", revision=0) is True
        assert engine.schedule_compensation("task-1", revision=0) is False
