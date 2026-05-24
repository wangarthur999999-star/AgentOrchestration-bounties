"""Tests for workflow expression validation and sandboxing (bounty #3396)."""

import pytest
from src.common.errors import WorkflowValidationError
from src.orchestrator.workflow import (
    ConditionExpression,
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def _passthrough(value=None):
    """Simple handler that returns the given value."""
    return value


class TestConditionExpression:
    def test_valid_operator_accepted(self):
        expr = ConditionExpression("eq", "a", "b")
        assert expr.operator == "eq"
        assert expr.validate() == []

    def test_unknown_operator_rejected(self):
        with pytest.raises(WorkflowValidationError, match="Unknown operator"):
            ConditionExpression("evil_op", "a", "b")

    def test_dunder_identifier_rejected(self):
        expr = ConditionExpression("eq", "__class__", "b")
        errors = expr.validate()
        assert len(errors) >= 1
        assert any("__class__" in e for e in errors)

    def test_nested_expression_validates_recursively(self):
        inner = ConditionExpression("eq", "__hidden__", "x")
        outer = ConditionExpression("and", inner, "y")
        errors = outer.validate()
        assert len(errors) >= 1

    def test_evaluate_eq_true(self):
        expr = ConditionExpression("eq", "x", 5)
        assert expr.evaluate({"x": 5}) is True

    def test_evaluate_eq_false(self):
        expr = ConditionExpression("eq", "x", 5)
        assert expr.evaluate({"x": 3}) is False

    def test_evaluate_gt(self):
        expr = ConditionExpression("gt", "count", 10)
        assert expr.evaluate({"count": 15}) is True
        assert expr.evaluate({"count": 5}) is False

    def test_evaluate_and(self):
        expr = ConditionExpression("and",
            ConditionExpression("gt", "a", 0),
            ConditionExpression("lt", "b", 100),
        )
        assert expr.evaluate({"a": 50, "b": 50}) is True

    def test_evaluate_or(self):
        expr = ConditionExpression("or",
            ConditionExpression("eq", "status", "ready"),
            ConditionExpression("eq", "force", True),
        )
        assert expr.evaluate({"status": "pending", "force": True}) is True

    def test_evaluate_not(self):
        expr = ConditionExpression("not", "flag", None)
        assert expr.evaluate({"flag": False}) is True

    def test_evaluate_in(self):
        expr = ConditionExpression("in", "role", ["admin", "owner"])
        assert expr.evaluate({"role": "admin"}) is True

    def test_evaluate_contains(self):
        expr = ConditionExpression("contains", "text", "hello")
        assert expr.evaluate({"text": "hello world"}) is True


class TestWorkflowStepValidation:
    def test_none_handler_rejected(self):
        step = WorkflowStep("bad", None)
        errors = step.validate()
        assert any("handler" in e for e in errors)

    def test_valid_step_passes(self):
        step = WorkflowStep("ok", _passthrough)
        assert step.validate() == []

    def test_step_with_valid_condition_passes(self):
        cond = ConditionExpression("eq", "var", 1)
        step = WorkflowStep("conditional", _passthrough, condition=cond)
        assert step.validate() == []

    def test_step_with_invalid_condition_fails(self):
        cond = ConditionExpression("eq", "__dunder__", 1)
        step = WorkflowStep("bad_condition", _passthrough, condition=cond)
        errors = step.validate()
        assert len(errors) >= 1


class TestWorkflowValidation:
    def test_empty_workflow_rejected(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("empty")
        errors = wf.validate()
        assert any("at least one step" in e for e in errors)

    def test_duplicate_step_name_rejected(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("dup_names")
        wf.add_step(WorkflowStep("step-a", _passthrough))
        wf.add_step(WorkflowStep("step-a", _passthrough))
        errors = wf.validate()
        assert any("Duplicate step name" in e for e in errors)

    def test_context_missing_variable_rejected(self):
        wm = WorkflowManager()
        cond = ConditionExpression("eq", "missing_var", 1)
        wf = wm.create_workflow("missing_context")
        step = WorkflowStep("s1", _passthrough, condition=cond)
        wm.add_step(wf.id, step)
        errors = wf.validate(context={"other": 1})
        assert any("missing_var" in e for e in errors)

    def test_context_variable_present_passes(self):
        wm = WorkflowManager()
        cond = ConditionExpression("eq", "present_var", 1)
        wf = wm.create_workflow("valid_context")
        step = WorkflowStep("s1", _passthrough, condition=cond)
        wm.add_step(wf.id, step)
        errors = wf.validate(context={"present_var": 1})
        assert len(errors) == 0


class TestRegistrationValidation:
    def test_add_step_to_running_workflow_rejected(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("running")
        wm.add_step(wf.id, WorkflowStep("s1", _passthrough))
        wf.status = StepStatus.RUNNING
        with pytest.raises(WorkflowValidationError, match="status is running"):
            wm.add_step(wf.id, WorkflowStep("s2", _passthrough))

    def test_add_step_valid_passes(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("ok")
        wm.add_step(wf.id, WorkflowStep("s1", _passthrough))
        assert len(wf.steps) == 1


class TestPreDispatchValidation:
    def test_valid_workflow_executes(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("simple")
        wm.add_step(wf.id, WorkflowStep("s1", _passthrough))
        assert wm.execute_workflow(wf.id) is True
        assert wf.status == StepStatus.COMPLETED

    def test_reentrant_execution_blocked(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("reentrant")
        wm.add_step(wf.id, WorkflowStep("s1", _passthrough))
        wf.status = StepStatus.RUNNING
        assert wm.execute_workflow(wf.id) is False

    def test_invalid_workflow_rejected_at_dispatch(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("invalid")
        cond = ConditionExpression("eq", "undefined_var", 1)
        wm.add_step(wf.id, WorkflowStep("s1", _passthrough, condition=cond))
        result = wm.execute_workflow(wf.id, context={})
        assert result is False
        assert wf.status == StepStatus.FAILED


class TestConditionalExecution:
    def test_step_skipped_when_condition_false(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("conditional")
        results = []
        cond = ConditionExpression("eq", "run_me", True)
        wm.add_step(wf.id, WorkflowStep("skip_if_false",
            lambda: results.append("ran"), condition=cond))
        ok = wm.execute_workflow(wf.id, context={"run_me": False})
        assert ok is True
        assert wf.steps[0].status == StepStatus.SKIPPED
        assert "ran" not in results

    def test_step_runs_when_condition_true(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("conditional_run")
        results = []
        cond = ConditionExpression("eq", "run_me", True)
        wm.add_step(wf.id, WorkflowStep("run_if_true",
            lambda: results.append("ran"), condition=cond))
        ok = wm.execute_workflow(wf.id, context={"run_me": True})
        assert ok is True
        assert wf.steps[0].status == StepStatus.COMPLETED
        assert "ran" in results

    def test_mixed_condition_workflow(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("mixed")
        results = []
        cond_true = ConditionExpression("eq", "x", 1)
        cond_false = ConditionExpression("eq", "x", 2)
        wm.add_step(wf.id, WorkflowStep("run", lambda: results.append("first"), condition=cond_true))
        wm.add_step(wf.id, WorkflowStep("skip", lambda: results.append("second"), condition=cond_false))
        wm.add_step(wf.id, WorkflowStep("always", lambda: results.append("third")))

        ok = wm.execute_workflow(wf.id, context={"x": 1})
        assert ok is True
        assert results == ["first", "third"]
        assert wf.steps[0].status == StepStatus.COMPLETED
        assert wf.steps[1].status == StepStatus.SKIPPED
        assert wf.steps[2].status == StepStatus.COMPLETED


class TestStepIsolation:
    def test_failed_step_preserves_previous_results(self):
        wm = WorkflowManager()
        wf = wm.create_workflow("isolation")
        wm.add_step(wf.id, WorkflowStep("good", lambda: "ok"))
        wm.add_step(wf.id, WorkflowStep("bad", lambda: (_ for _ in ()).throw(ValueError("boom"))))

        ok = wm.execute_workflow(wf.id)
        assert ok is False
        assert wf.steps[0].status == StepStatus.COMPLETED
        assert wf.steps[0].result == "ok"
        assert wf.steps[1].status == StepStatus.FAILED
        assert wf.status == StepStatus.FAILED
