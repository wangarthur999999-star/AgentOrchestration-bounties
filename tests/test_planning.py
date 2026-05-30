"""Tests for planning engine."""

import json

import pytest

from src.orchestrator.planning import (
    ExecutionPlan,
    PlanStep,
    PlanningEngine,
    PlanningError,
)


class TestPlanStep:
    def test_creation(self):
        step = PlanStep(
            step_id="1",
            description="Review code",
            assigned_agent="reviewer",
            dependencies=[],
            parallel_group=1,
            expected_output="JSON list of issues",
        )
        assert step.step_id == "1"
        assert step.assigned_agent == "reviewer"
        assert step.parallel_group == 1


class TestExecutionPlan:
    def test_get_parallel_groups(self):
        steps = [
            PlanStep("1", "Task A", "agent-a", parallel_group=1),
            PlanStep("2", "Task B", "agent-b", parallel_group=1),
            PlanStep("3", "Task C", "agent-c", parallel_group=0),
            PlanStep("4", "Task D", "agent-d", parallel_group=2),
        ]
        plan = ExecutionPlan(goal="test", steps=steps)

        groups = plan.get_parallel_groups()
        assert 1 in groups
        assert len(groups[1]) == 2
        assert 2 in groups
        assert len(groups[2]) == 1

    def test_get_step_order_respects_dependencies(self):
        steps = [
            PlanStep("1", "First", "agent-a"),
            PlanStep("2", "Second", "agent-b", dependencies=["1"]),
            PlanStep("3", "Third", "agent-c", dependencies=["2"]),
        ]
        plan = ExecutionPlan(goal="test", steps=steps)
        order = plan.get_step_order()

        ids = [s.step_id for s in order if s.step_id != "synthesis"]
        assert ids.index("1") < ids.index("2")
        assert ids.index("2") < ids.index("3")

    def test_get_step_order_with_synthesis(self):
        steps = [
            PlanStep("1", "A", "agent-a"),
            PlanStep("2", "B", "agent-b"),
        ]
        synthesis = PlanStep("final", "Synthesize", "agent-c", dependencies=["1", "2"])
        plan = ExecutionPlan(goal="test", steps=steps, synthesis_step=synthesis)

        order = plan.get_step_order()
        assert order[-1].step_id == "final"


class TestPlanningEngine:
    def test_parse_valid_json_response(self):
        engine = PlanningEngine(api_key="test-key")
        raw = json.dumps({
            "steps": [
                {"step_id": "1", "description": "Review", "assigned_agent": "reviewer",
                 "dependencies": [], "parallel_group": 0, "expected_output": "Issues"},
                {"step_id": "2", "description": "Test", "assigned_agent": "tester",
                 "dependencies": ["1"], "parallel_group": 0, "expected_output": "Tests"},
            ],
            "synthesis": {"step_id": "3", "description": "Merge", "assigned_agent": "reviewer",
                          "dependencies": ["1", "2"], "expected_output": "Report"},
        })
        agents = [{"name": "reviewer", "description": "reviews"}, {"name": "tester", "description": "tests"}]

        plan = engine._parse_response(raw, "Review and test", agents)
        assert len(plan.steps) == 2
        assert plan.synthesis_step is not None
        assert plan.synthesis_step.step_id == "3"

    def test_parse_response_with_markdown_fences(self):
        engine = PlanningEngine(api_key="test-key")
        raw = "```json\n" + json.dumps({
            "steps": [{"step_id": "1", "description": "Do", "assigned_agent": "agent",
                        "dependencies": [], "parallel_group": 0, "expected_output": "Result"}],
        }) + "\n```"
        agents = [{"name": "agent", "description": "does things"}]

        plan = engine._parse_response(raw, "Do something", agents)
        assert len(plan.steps) == 1

    def test_validate_plan_unknown_agent(self):
        engine = PlanningEngine(api_key="test-key")
        steps = [PlanStep("1", "Do", "nonexistent")]
        plan = ExecutionPlan(goal="test", steps=steps)
        agents = [{"name": "real-agent", "description": "exists"}]

        with pytest.raises(PlanningError, match="unknown agent"):
            engine._validate_plan(plan, agents)

    def test_validate_plan_unknown_dependency(self):
        engine = PlanningEngine(api_key="test-key")
        steps = [PlanStep("1", "Do", "agent-a", dependencies=["nonexistent"])]
        plan = ExecutionPlan(goal="test", steps=steps)
        agents = [{"name": "agent-a", "description": "exists"}]

        with pytest.raises(PlanningError, match="unknown step"):
            engine._validate_plan(plan, agents)

    def test_validate_plan_self_dependency(self):
        engine = PlanningEngine(api_key="test-key")
        steps = [PlanStep("1", "Do", "agent-a", dependencies=["1"])]
        plan = ExecutionPlan(goal="test", steps=steps)
        agents = [{"name": "agent-a", "description": "exists"}]

        with pytest.raises(PlanningError, match="depends on itself"):
            engine._validate_plan(plan, agents)

    def test_validate_plan_valid(self):
        engine = PlanningEngine(api_key="test-key")
        steps = [
            PlanStep("1", "A", "agent-a"),
            PlanStep("2", "B", "agent-b", dependencies=["1"]),
        ]
        synthesis = PlanStep("final", "S", "agent-a", dependencies=["1", "2"])
        plan = ExecutionPlan(goal="test", steps=steps, synthesis_step=synthesis)
        agents = [{"name": "agent-a", "description": "a"}, {"name": "agent-b", "description": "b"}]

        engine._validate_plan(plan, agents)  # Should not raise

    def test_plan_to_workflow(self):
        engine = PlanningEngine(api_key="test-key")
        steps = [
            PlanStep("1", "Step 1", "agent-a"),
            PlanStep("2", "Step 2", "agent-b", dependencies=["1"]),
        ]
        plan = ExecutionPlan(goal="test workflow", steps=steps)
        workflow = engine.plan_to_workflow(plan)

        assert workflow is not None
        assert len(workflow.steps) == 2
        assert workflow.name.startswith("plan_")

    def test_plan_summary(self):
        steps = [
            PlanStep("1", "First task", "agent-a", parallel_group=1),
            PlanStep("2", "Second task", "agent-b", dependencies=["1"]),
        ]
        synthesis = PlanStep("final", "Merge", "agent-a", dependencies=["1", "2"])
        plan = ExecutionPlan(goal="Test goal", steps=steps, synthesis_step=synthesis)

        engine = PlanningEngine(api_key="test-key")
        summary = engine.plan_summary(plan)

        assert "Test goal" in summary
        assert "agent-a" in summary
        assert "agent-b" in summary
        assert "parallel group 1" in summary
