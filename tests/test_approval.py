"""Tests for Human-in-the-loop approval system."""

import asyncio

import pytest

from src.orchestrator.approval import (
    ApprovalGateway,
    ApprovalHandler,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    AutoApprovalHandler,
    CLIApprovalHandler,
)
from src.orchestrator.multi_agent import ManagerWorkerStrategy
from src.orchestrator.protocol import AgentMessage, MessageBus, MessageType


class TestApprovalRequest:
    def test_creation(self):
        req = ApprovalRequest(
            id="req-1",
            agent_id="worker-1",
            action="Send email to 500 recipients",
            reasoning="Campaign is ready and audience is active",
            context={"list_id": "main", "subject": "Sale!"},
            options=["Send now", "Schedule for later", "Cancel"],
        )
        assert req.id == "req-1"
        assert req.agent_id == "worker-1"
        assert len(req.options) == 3

    def test_summary(self):
        req = ApprovalRequest(
            id="req-1",
            agent_id="agent-x",
            action="Deploy to production",
            reasoning="All tests pass",
        )
        summary = req.summary()
        assert "agent-x" in summary
        assert "Deploy to production" in summary
        assert "All tests pass" in summary


class TestAutoApprovalHandler:
    @pytest.mark.asyncio
    async def test_auto_approve(self):
        handler = AutoApprovalHandler(ApprovalStatus.APPROVED)
        req = ApprovalRequest("r1", "a1", "do stuff", "because")
        resp = await handler.request_approval(req)
        assert resp.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_auto_reject(self):
        handler = AutoApprovalHandler(ApprovalStatus.REJECTED)
        req = ApprovalRequest("r1", "a1", "do stuff", "because")
        resp = await handler.request_approval(req)
        assert resp.status == ApprovalStatus.REJECTED


class TestApprovalGateway:
    @pytest.mark.asyncio
    async def test_ask_returns_response(self):
        handler = AutoApprovalHandler(ApprovalStatus.APPROVED)
        gateway = ApprovalGateway(handler)
        resp = await gateway.ask("agent-1", "Do thing", "Good reason")
        assert resp.status == ApprovalStatus.APPROVED
        assert gateway.total_requests == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_default(self):
        class SlowHandler(ApprovalHandler):
            async def request_approval(self, req):
                await asyncio.sleep(10)
                return ApprovalResponse(req.id, ApprovalStatus.APPROVED)

        gateway = ApprovalGateway(SlowHandler(), default_timeout=0.05)
        resp = await gateway.ask("a", "action", "reason", timeout=0.01)
        assert resp.status == ApprovalStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_history_accumulates(self):
        handler = AutoApprovalHandler(ApprovalStatus.APPROVED)
        gateway = ApprovalGateway(handler)
        await gateway.ask("a1", "one", "r1")
        await gateway.ask("a2", "two", "r2")
        assert gateway.total_requests == 2
        assert len(gateway.history()) == 2


class TestManagerWorkerWithApproval:
    """Integration: ManagerWorkerStrategy with auto-approval gateway."""

    @pytest.mark.asyncio
    async def test_auto_approved_execution(self):
        handler = AutoApprovalHandler(ApprovalStatus.APPROVED)
        gateway = ApprovalGateway(handler)

        class FakeAgent:
            def __init__(self, agent_id, name):
                self.agent_id = agent_id
                self.name = name
                self.outbox = []

            async def setup(self):
                pass

            async def cleanup(self):
                pass

            async def handle_message(self, msg):
                return AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=self.agent_id,
                    payload={"content": f"[{self.name}] processed: {msg.payload.get('prompt', '')[:50]}"},
                )

        manager = FakeAgent("mgr", "Manager")
        worker_a = FakeAgent("wa", "WorkerA")
        worker_b = FakeAgent("wb", "WorkerB")

        # Override manager's handle_message to return decomposition with approval flag
        async def mgr_handle(msg):
            return AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="mgr",
                payload={"content": '{"subtasks": [{"worker": "wa", "task": "safe task", "require_approval": false}, {"worker": "wb", "task": "dangerous task", "require_approval": true}]}'},
            )
        manager.handle_message = mgr_handle

        strategy = ManagerWorkerStrategy(
            manager_agent_id="mgr",
            worker_agent_ids=["wa", "wb"],
            approval_gateway=gateway,
        )

        agents = {"mgr": manager, "wa": worker_a, "wb": worker_b}
        from src.orchestrator.memory import SharedBlackboard
        bb = SharedBlackboard("test-team")
        bus = MessageBus()

        result = await strategy.execute(agents, bb, bus, {"prompt": "test task"})
        assert result["status"] == "completed"
        assert "wa" in result["worker_results"]

    @pytest.mark.asyncio
    async def test_rejected_task_blocked(self):
        handler = AutoApprovalHandler(ApprovalStatus.REJECTED)
        gateway = ApprovalGateway(handler)

        class FakeAgent:
            def __init__(self, agent_id, name):
                self.agent_id = agent_id
                self.name = name
                self.outbox = []

            async def setup(self):
                pass

            async def cleanup(self):
                pass

            async def handle_message(self, msg):
                return AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=self.agent_id,
                    payload={"content": f"[{self.name}] done"},
                )

        manager = FakeAgent("mgr", "Manager")
        worker = FakeAgent("w", "Worker")

        async def mgr_handle(msg):
            return AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="mgr",
                payload={"content": '{"subtasks": [{"worker": "w", "task": "blocked task", "require_approval": true}]}'},
            )
        manager.handle_message = mgr_handle

        strategy = ManagerWorkerStrategy(
            manager_agent_id="mgr",
            worker_agent_ids=["w"],
            approval_gateway=gateway,
        )

        from src.orchestrator.memory import SharedBlackboard
        bb = SharedBlackboard("test-team")
        bus = MessageBus()

        result = await strategy.execute(agents={"mgr": manager, "w": worker}, blackboard=bb, bus=bus, initial_task={"prompt": "test"})
        assert "REJECTED" in result["worker_results"]["w"]


class TestConversationStrategyApproval:
    @pytest.mark.asyncio
    async def test_no_gateway_auto_approves(self):
        strategy = ManagerWorkerStrategy(manager_agent_id="m", worker_agent_ids=["w"])
        # Without gateway, approval always returns True
        approved = await strategy._request_approval("a", "act", "reason")
        assert approved is True
