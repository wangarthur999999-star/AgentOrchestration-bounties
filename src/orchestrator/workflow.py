"""Workflow Manager — Defines and executes multi-step agent workflows.

Validation is enforced at two points to prevent side-effect leaks:
1. Registration time (add_step) — rejects malformed conditions and disallowed operators
2. Pre-dispatch (execute_workflow) — validates the full graph against the runtime context
"""

import ast
import logging
import operator as builtin_ops
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from src.common.errors import ExpressionValidationError, WorkflowValidationError

logger = logging.getLogger(__name__)

EXPRESSION_ALLOWED_OPS: Set[str] = {
    "eq", "neq", "gt", "gte", "lt", "lte",
    "and", "or", "not", "in", "contains", "matches",
}

OP_FUNCTIONS = {
    "eq": builtin_ops.eq, "neq": builtin_ops.ne,
    "gt": builtin_ops.gt, "gte": builtin_ops.ge,
    "lt": builtin_ops.lt, "lte": builtin_ops.le,
}

AST_ALLOWED_NODES = frozenset({
    ast.Expression, ast.Compare, ast.BoolOp, ast.UnaryOp,
    ast.Name, ast.Constant, ast.Tuple, ast.List,
})

AST_OP_MAP = {
    ast.Eq: builtin_ops.eq, ast.NotEq: builtin_ops.ne,
    ast.Lt: builtin_ops.lt, ast.LtE: builtin_ops.le,
    ast.Gt: builtin_ops.gt, ast.GtE: builtin_ops.ge,
    ast.And: lambda a, b: a and b, ast.Or: lambda a, b: a or b,
    ast.Not: builtin_ops.not_,
}


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConditionExpression:
    """A validated condition expression for workflow branching.

    Only whitelisted operators are allowed. Expression trees are validated
    recursively to prevent side-effectful operations from leaking into
    condition evaluation.
    """

    def __init__(
        self,
        operator: str,
        left: Any,
        right: Any = None,
        expr_id: Optional[str] = None,
    ):
        if operator not in EXPRESSION_ALLOWED_OPS:
            raise WorkflowValidationError(
                f"Unknown operator '{operator}'. Allowed: {sorted(EXPRESSION_ALLOWED_OPS)}"
            )
        self.id = expr_id or str(uuid4())
        self.operator = operator
        self.left = left
        self.right = right

    def validate(self) -> List[str]:
        errors: List[str] = []
        self._validate_node(self, errors)
        return errors

    def _validate_node(self, node: "ConditionExpression", errors: List[str]) -> None:
        for side in [node.left, node.right]:
            if isinstance(side, ConditionExpression):
                self._validate_node(side, errors)
            elif isinstance(side, str) and side.startswith("__"):
                errors.append(
                    f"Expression '{node.id}': dunder identifier not allowed: '{side}'"
                )

    def evaluate(self, context: Dict[str, Any]) -> bool:
        return self._eval_node(self, context)

    def _eval_node(self, node: "ConditionExpression", context: Dict[str, Any]) -> Any:
        left = node.left
        right = node.right
        if isinstance(left, ConditionExpression):
            left = self._eval_node(left, context)
        if isinstance(right, ConditionExpression):
            right = self._eval_node(right, context)
        if isinstance(left, str) and left in context:
            left = context[left]
        if isinstance(right, str) and right in context:
            right = context[right]

        op = node.operator
        if op in OP_FUNCTIONS:
            return OP_FUNCTIONS[op](left, right)
        if op == "and":
            return bool(left) and bool(right)
        if op == "or":
            return bool(left) or bool(right)
        if op == "not":
            return not bool(left)
        if op == "in":
            return left in right
        if op == "contains":
            return right in left
        if op == "matches":
            import re
            return bool(re.search(str(right), str(left)))
        raise WorkflowValidationError(f"Unsupported operator for eval: {op}")


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        condition: Optional[ConditionExpression] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.condition = condition
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.handler is None:
            errors.append(f"Step '{self.name}': handler must not be None")
        if self.condition is not None:
            errors.extend(self.condition.validate())
        return errors


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def validate(self, context: Optional[Dict[str, Any]] = None) -> List[str]:
        errors: List[str] = []
        seen_ids: Set[str] = set()
        seen_names: Set[str] = set()
        if not self.steps:
            errors.append(f"Workflow '{self.name}': must have at least one step")
        for step in self.steps:
            if step.id in seen_ids:
                errors.append(f"Duplicate step ID: {step.id}")
            seen_ids.add(step.id)
            if step.name in seen_names:
                errors.append(f"Duplicate step name: '{step.name}'")
            seen_names.add(step.name)
            errors.extend(step.validate())
        if context is not None:
            errors.extend(self._validate_context(context))
        return errors

    def _validate_context(self, context: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for step in self.steps:
            if step.condition is not None:
                refs = self._collect_refs(step.condition)
                for ref in refs:
                    if ref not in context:
                        errors.append(
                            f"Step '{step.name}': condition references "
                            f"undefined variable '{ref}'"
                        )
        return errors

    @staticmethod
    def _collect_refs(expr: ConditionExpression) -> Set[str]:
        refs: Set[str] = set()
        for side in [expr.left, expr.right]:
            if isinstance(side, ConditionExpression):
                refs.update(Workflow._collect_refs(side))
            elif isinstance(side, str) and not side.startswith(("'", '"')):
                refs.add(side)
        return refs


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._lock = Lock()

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        with self._lock:
            self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        with self._lock:
            return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        with self._lock:
            return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock:
            return self._workflows.pop(workflow_id, None) is not None

    def add_step(self, workflow_id: str, step: WorkflowStep) -> "WorkflowManager":
        with self._lock:
            workflow = self._workflows.get(workflow_id)
            if not workflow:
                raise WorkflowValidationError(
                    f"Workflow {workflow_id} not found for add_step"
                )
            if workflow.status != StepStatus.PENDING:
                raise WorkflowValidationError(
                    f"Cannot add step to workflow '{workflow.name}': "
                    f"status is {workflow.status.value}"
                )
            errors = step.validate()
            if errors:
                logger.warning(
                    "Registration validation failed for step '%s': %s",
                    step.name, errors,
                )
                raise WorkflowValidationError(
                    f"Step '{step.name}' validation failed: {'; '.join(errors)}"
                )
            workflow.add_step(step)
        return self

    def execute_workflow(
        self, workflow_id: str, context: Optional[Dict[str, Any]] = None
    ) -> bool:
        with self._lock:
            workflow = self._workflows.get(workflow_id)
            if not workflow:
                return False
            if workflow.status == StepStatus.RUNNING:
                logger.warning(
                    "Workflow '%s' is already running; rejecting re-entrant execution",
                    workflow.name,
                )
                return False

            errors = workflow.validate(context=context)
            if errors:
                logger.error(
                    "Pre-dispatch validation failed for workflow '%s': %s",
                    workflow.name, errors,
                )
                workflow.status = StepStatus.FAILED
                return False

            workflow.status = StepStatus.RUNNING

        for step in workflow.steps:
            if step.condition is not None and context is not None:
                try:
                    should_run = step.condition.evaluate(context)
                except Exception as exc:
                    step.error = f"Condition eval failed: {exc}"
                    step.status = StepStatus.FAILED
                    logger.error("Step '%s' condition evaluation failed: %s", step.name, exc)
                    with self._lock:
                        workflow.status = StepStatus.FAILED
                    return False
                if not should_run:
                    step.status = StepStatus.SKIPPED
                    logger.info(
                        "Step '%s' skipped: condition evaluated to false", step.name
                    )
                    continue

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                with self._lock:
                    workflow.status = StepStatus.FAILED
                return False

        with self._lock:
            workflow.status = StepStatus.COMPLETED
        return True

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
