"""Tests for cancel propagation guard — bounty #3695."""

from src.orchestrator.engine import OrchestrationEngine


class TestCancelPropagation:
    def test_cancel_marks_task(self):
        engine = OrchestrationEngine()
        assert engine.cancel("task-1") is True
        assert engine.is_cancelled("task-1") is True

    def test_is_cancelled_unknown_returns_false(self):
        engine = OrchestrationEngine()
        assert engine.is_cancelled("nonexistent") is False

    def test_clear_cancelled_removes_mark(self):
        engine = OrchestrationEngine()
        engine.cancel("task-1")
        assert engine.clear_cancelled("task-1") is True
        assert engine.is_cancelled("task-1") is False

    def test_clear_cancelled_unknown_returns_false(self):
        engine = OrchestrationEngine()
        assert engine.clear_cancelled("nonexistent") is False

    def test_retry_task_skips_when_task_cancelled(self):
        engine = OrchestrationEngine()
        task = {"id": "task-1", "type": "test", "target_agent": "agent-1"}
        engine.cancel("task-1")
        result = engine.retry_task(task)
        assert result is None

    def test_retry_task_skips_when_parent_cancelled(self):
        engine = OrchestrationEngine()
        engine.cancel("parent-1")
        task = {"id": "child-1", "parent_id": "parent-1", "type": "test", "target_agent": "agent-1"}
        result = engine.retry_task(task)
        assert result is None

    def test_retry_task_succeeds_when_not_cancelled(self):
        engine = OrchestrationEngine()
        task = {"id": "task-1", "type": "test", "target_agent": "agent-1"}
        result = engine.retry_task(task)
        assert result is not None

    def test_retry_task_succeeds_when_parent_not_cancelled(self):
        engine = OrchestrationEngine()
        task = {"id": "child-1", "parent_id": "parent-2", "type": "test", "target_agent": "agent-1"}
        result = engine.retry_task(task)
        assert result is not None

    def test_cancel_idempotent(self):
        engine = OrchestrationEngine()
        assert engine.cancel("task-1") is True
        assert engine.cancel("task-1") is True
        assert engine.is_cancelled("task-1") is True

    def test_clear_cancelled_after_retry_allows_re_enqueue(self):
        engine = OrchestrationEngine()
        task = {"id": "task-1", "type": "test", "target_agent": "agent-1"}
        engine.cancel("task-1")
        assert engine.retry_task(task) is None
        engine.clear_cancelled("task-1")
        result = engine.retry_task(task)
        assert result is not None
