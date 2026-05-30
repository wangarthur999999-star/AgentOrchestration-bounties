"""Planning Engine — LLM-driven task decomposition and plan-to-workflow conversion."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from src.orchestrator.workflow import Workflow, WorkflowManager, WorkflowStep

logger = logging.getLogger(__name__)

PLANNING_SYSTEM_PROMPT = """You are a task planning AI. Given a goal and available agents, decompose the goal into steps.

Output ONLY valid JSON with this exact structure:
{
  "steps": [
    {
      "step_id": "1",
      "description": "What this step does in detail",
      "assigned_agent": "agent_name",
      "dependencies": [],
      "parallel_group": 0,
      "expected_output": "Description of expected output format"
    }
  ],
  "synthesis": {
    "step_id": "final",
    "description": "Merge and synthesize all findings",
    "assigned_agent": "agent_name",
    "dependencies": ["all_step_ids"],
    "parallel_group": 0,
    "expected_output": "Final synthesized result"
  }
}

Rules:
- Assign each step to exactly one available agent by name
- Steps with no dependencies and same parallel_group (>0) run concurrently
- A step can only depend on steps with lower step_ids
- Max 8 steps (excluding synthesis)
- The synthesis step has dependencies on ALL preceding steps
- Be specific about what each step produces
"""


@dataclass
class PlanStep:
    step_id: str
    description: str
    assigned_agent: str
    dependencies: list[str] = field(default_factory=list)
    parallel_group: int = 0
    expected_output: str = ""


@dataclass
class ExecutionPlan:
    goal: str
    steps: list[PlanStep]
    synthesis_step: Optional[PlanStep] = None

    def get_parallel_groups(self) -> dict[int, list[PlanStep]]:
        """Group steps by their parallel_group number."""
        groups: dict[int, list[PlanStep]] = {}
        for step in self.steps:
            if step.parallel_group > 0:
                groups.setdefault(step.parallel_group, []).append(step)
        return groups

    def get_step_order(self) -> list[PlanStep]:
        """Return steps in dependency-respecting order."""
        resolved = []
        remaining = list(self.steps)
        resolved_ids: set[str] = set()

        while remaining:
            ready = [
                s for s in remaining
                if all(d in resolved_ids for d in s.dependencies)
            ]
            if not ready:
                # Circular dependency or missing dep — add remaining as-is
                resolved.extend(remaining)
                break
            resolved.extend(ready)
            for s in ready:
                resolved_ids.add(s.step_id)
                remaining.remove(s)

        if self.synthesis_step:
            resolved.append(self.synthesis_step)
        return resolved


class PlanningError(Exception):
    """Raised when planning fails."""
    pass


class PlanningEngine:
    """Uses an LLM to decompose high-level goals into structured execution plans."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client: Optional[AsyncOpenAI] = None

    async def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    async def plan(
        self,
        goal: str,
        available_agents: list[dict],
        max_steps: int = 8,
    ) -> ExecutionPlan:
        """Decompose a goal into an ExecutionPlan using the LLM."""
        client = await self._get_client()

        agent_list = json.dumps(available_agents, indent=2)
        user_prompt = (
            f"Available agents:\n{agent_list}\n\n"
            f"Goal: {goal}\n\n"
            f"Max {max_steps} steps."
        )

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=2048,
                temperature=0.2,
            )
            raw = response.choices[0].message.content or "{}"
            plan = self._parse_response(raw, goal, available_agents)
            self._validate_plan(plan, available_agents)
            return plan
        except json.JSONDecodeError as e:
            raise PlanningError(f"Failed to parse LLM plan output: {e}\nRaw: {raw[:500]}")
        except Exception as e:
            if isinstance(e, PlanningError):
                raise
            raise PlanningError(f"Planning failed: {e}")

    def _parse_response(
        self, raw: str, goal: str, agents: list[dict],
    ) -> ExecutionPlan:
        """Parse the LLM's JSON response into an ExecutionPlan."""
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(raw)
        steps = []
        for s in data.get("steps", []):
            steps.append(PlanStep(
                step_id=s.get("step_id", str(len(steps) + 1)),
                description=s.get("description", ""),
                assigned_agent=s.get("assigned_agent", agents[0]["name"] if agents else ""),
                dependencies=s.get("dependencies", []),
                parallel_group=s.get("parallel_group", 0),
                expected_output=s.get("expected_output", ""),
            ))

        synthesis = None
        if "synthesis" in data:
            s = data["synthesis"]
            synthesis = PlanStep(
                step_id=s.get("step_id", "synthesis"),
                description=s.get("description", "Synthesize results"),
                assigned_agent=s.get("assigned_agent", agents[0]["name"] if agents else ""),
                dependencies=s.get("dependencies", [st.step_id for st in steps]),
                parallel_group=0,
                expected_output=s.get("expected_output", "Final synthesized result"),
            )

        return ExecutionPlan(goal=goal, steps=steps, synthesis_step=synthesis)

    def _validate_plan(self, plan: ExecutionPlan, agents: list[dict]) -> None:
        """Validate the plan for consistency."""
        agent_names = {a["name"] for a in agents}
        step_ids = {s.step_id for s in plan.steps}

        for step in plan.steps:
            if step.assigned_agent not in agent_names:
                raise PlanningError(
                    f"Step {step.step_id} assigned to unknown agent '{step.assigned_agent}'"
                )
            for dep in step.dependencies:
                if dep not in step_ids:
                    raise PlanningError(
                        f"Step {step.step_id} depends on unknown step '{dep}'"
                    )
                if dep == step.step_id:
                    raise PlanningError(
                        f"Step {step.step_id} depends on itself"
                    )

        if plan.synthesis_step:
            for dep in plan.synthesis_step.dependencies:
                if dep not in step_ids:
                    raise PlanningError(
                        f"Synthesis step depends on unknown step '{dep}'"
                    )

    def plan_to_workflow(self, plan: ExecutionPlan) -> Workflow:
        """Convert an ExecutionPlan to an executable Workflow."""
        wm = WorkflowManager()
        workflow = wm.create_workflow(
            name=f"plan_{plan.goal[:40].replace(' ', '_')}",
            description=plan.goal,
        )

        # Create a step registry for dependency resolution
        step_registry: dict[str, WorkflowStep] = {}

        # Process sequential steps first, then parallel groups
        for step in plan.steps:
            def make_handler(s: PlanStep):
                return lambda: {"step": s.step_id, "assigned": s.assigned_agent}
            ws = WorkflowStep(name=step.step_id, handler=make_handler(step))
            step_registry[step.step_id] = ws
            workflow.add_step(ws)

        if plan.synthesis_step:
            def synth_handler():
                return {"step": "synthesis", "assigned": plan.synthesis_step.assigned_agent}
            synth_ws = WorkflowStep(
                name=plan.synthesis_step.step_id, handler=synth_handler,
            )
            workflow.add_step(synth_ws)

        return workflow

    def plan_summary(self, plan: ExecutionPlan) -> str:
        """Return a human-readable summary of the plan."""
        lines = [f"Plan for: {plan.goal}", "-" * 40]
        for step in plan.steps:
            deps = f" (after: {', '.join(step.dependencies)})" if step.dependencies else ""
            para = f" [parallel group {step.parallel_group}]" if step.parallel_group > 0 else ""
            lines.append(
                f"  {step.step_id}. [{step.assigned_agent}]{para}{deps}: {step.description}"
            )
        if plan.synthesis_step:
            lines.append(f"  {plan.synthesis_step.step_id}. SYNTHESIS: {plan.synthesis_step.description}")
        return "\n".join(lines)
