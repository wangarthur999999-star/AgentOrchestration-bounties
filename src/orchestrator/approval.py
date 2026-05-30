"""Human-in-the-loop approval gateway for multi-agent orchestration.

Allows strategies to pause at critical decision points and wait for
human input before continuing. Supports CLI, API, and webhook channels.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    MODIFIED = "modified"


@dataclass
class ApprovalRequest:
    """A request for human approval at a decision point."""

    id: str
    agent_id: str
    action: str  # what the agent wants to do
    reasoning: str  # why the agent wants to do it
    context: dict = field(default_factory=dict)  # additional context
    options: list[str] = field(default_factory=list)  # if agent proposes alternatives
    timeout: float = 300.0  # 5 minutes
    created_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        lines = [
            f"┌─ Approval Required ─────────────────────────────",
            f"│ Agent: {self.agent_id}",
            f"│ Action: {self.action}",
            f"│ Reason: {self.reasoning}",
        ]
        if self.options:
            lines.append(f"│ Options: {', '.join(self.options)}")
        if self.context:
            ctx = json.dumps(self.context, ensure_ascii=False, indent=2)
            for line in ctx.split("\n"):
                lines.append(f"│ {line}")
        lines.append("└──────────────────────────────────────────────────")
        return "\n".join(lines)


@dataclass
class ApprovalResponse:
    """Human response to an approval request."""

    request_id: str
    status: ApprovalStatus
    feedback: str = ""
    modified_params: dict = field(default_factory=dict)
    responder: str = "human"


class ApprovalHandler(ABC):
    """Abstract handler — implement for CLI, API, webhook, etc."""

    @abstractmethod
    async def request_approval(self, req: ApprovalRequest) -> ApprovalResponse:
        ...


class CLIApprovalHandler(ApprovalHandler):
    """Interactive terminal-based approval."""

    async def request_approval(self, req: ApprovalRequest) -> ApprovalResponse:
        print(req.summary())
        print()

        choices = {"y": "approved", "n": "rejected", "m": "modified"}

        while True:
            choice = input("Approve? [y]es / [n]o / [m]odify: ").strip().lower()
            if choice in ("y", "yes"):
                return ApprovalResponse(
                    request_id=req.id,
                    status=ApprovalStatus.APPROVED,
                    feedback="Approved by human",
                )
            elif choice in ("n", "no"):
                return ApprovalResponse(
                    request_id=req.id,
                    status=ApprovalStatus.REJECTED,
                    feedback=input("Rejection reason: ") or "Rejected by human",
                )
            elif choice in ("m", "modify"):
                try:
                    mod = input("Enter modified params as JSON: ")
                    return ApprovalResponse(
                        request_id=req.id,
                        status=ApprovalStatus.MODIFIED,
                        modified_params=json.loads(mod) if mod else {},
                        feedback="Modified by human",
                    )
                except json.JSONDecodeError:
                    print("Invalid JSON. Try again.")
            else:
                print("Please enter 'y', 'n', or 'm'.")


class AutoApprovalHandler(ApprovalHandler):
    """Auto-approve or auto-reject — for testing and non-critical paths."""

    def __init__(self, default: ApprovalStatus = ApprovalStatus.APPROVED):
        self.default = default

    async def request_approval(self, req: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(
            request_id=req.id,
            status=self.default,
            feedback=f"Auto {self.default.value}",
        )


class ApprovalGateway:
    """Central approval gateway — routes requests to handlers with timeout.

    Usage:
        gateway = ApprovalGateway(CLIApprovalHandler(), default_timeout=120)

        # In a strategy:
        if strategy.approval_gateway:
            resp = await strategy.approval_gateway.ask(
                agent_id="worker-1",
                action="Send email campaign",
                reasoning="Campaign is ready and scheduled for optimal time",
            )
            if resp.status == ApprovalStatus.APPROVED:
                # proceed
    """

    def __init__(
        self,
        handler: ApprovalHandler,
        default_timeout: float = 300.0,
        on_timeout: ApprovalStatus = ApprovalStatus.REJECTED,
    ):
        self.handler = handler
        self.default_timeout = default_timeout
        self.on_timeout = on_timeout
        self._counter = 0
        self._history: list[tuple[ApprovalRequest, ApprovalResponse]] = []

    async def ask(
        self,
        agent_id: str,
        action: str,
        reasoning: str,
        context: dict = None,
        options: list[str] = None,
        timeout: float = None,
    ) -> ApprovalResponse:
        """Send an approval request and wait for a response."""
        self._counter += 1
        req = ApprovalRequest(
            id=f"approval_{self._counter}",
            agent_id=agent_id,
            action=action,
            reasoning=reasoning,
            context=context or {},
            options=options or [],
            timeout=timeout or self.default_timeout,
        )

        try:
            resp = await asyncio.wait_for(
                self.handler.request_approval(req),
                timeout=req.timeout,
            )
        except asyncio.TimeoutError:
            resp = ApprovalResponse(
                request_id=req.id,
                status=ApprovalStatus.TIMED_OUT,
                feedback=f"Timed out after {req.timeout}s",
            )

        self._history.append((req, resp))
        return resp

    def history(self) -> list[dict]:
        """Return approval history as dicts."""
        return [
            {"request": {"agent": r.agent_id, "action": r.action}, "response": s.status.value}
            for r, s in self._history
        ]

    @property
    def total_requests(self) -> int:
        return len(self._history)
