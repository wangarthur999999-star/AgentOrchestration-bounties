"""Tests for agent message protocol."""

import pytest

from src.orchestrator.protocol import AgentMessage, MessageBus, MessageType


class TestAgentMessage:
    def test_default_values(self):
        msg = AgentMessage()
        assert msg.id
        assert msg.type == MessageType.TASK
        assert msg.from_agent == ""
        assert msg.timestamp > 0

    def test_custom_message(self):
        msg = AgentMessage(
            type=MessageType.RESPONSE,
            from_agent="agent-1",
            to_agent="agent-2",
            team_id="team-a",
            payload={"result": 42},
            context_keys=["key1"],
            reply_to="msg-123",
        )
        assert msg.type == MessageType.RESPONSE
        assert msg.from_agent == "agent-1"
        assert msg.to_agent == "agent-2"
        assert msg.team_id == "team-a"
        assert msg.payload["result"] == 42
        assert "key1" in msg.context_keys
        assert msg.reply_to == "msg-123"

    def test_unique_ids(self):
        msg1 = AgentMessage()
        msg2 = AgentMessage()
        assert msg1.id != msg2.id


class TestMessageBus:
    def test_subscribe_and_publish(self):
        bus = MessageBus()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe("agent-1", handler)
        msg = AgentMessage(to_agent="agent-1", payload={"x": 1})
        bus.publish_sync(msg)

        assert len(received) == 1
        assert received[0].payload["x"] == 1

    def test_broadcast(self):
        bus = MessageBus()
        received_a = []
        received_b = []

        bus.subscribe("agent-a", lambda m: received_a.append(m))
        bus.subscribe("agent-b", lambda m: received_b.append(m))

        bus.broadcast(AgentMessage(from_agent="system", payload={"alert": "test"}))

        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_unsubscribe(self):
        bus = MessageBus()
        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe("agent-1", handler)
        bus.unsubscribe("agent-1", handler)

        bus.publish_sync(AgentMessage(to_agent="agent-1"))
        assert len(received) == 0

    def test_conversation_history(self):
        bus = MessageBus()
        bus.publish_sync(AgentMessage(team_id="team-x", from_agent="a"))
        bus.publish_sync(AgentMessage(team_id="team-x", from_agent="b"))
        bus.publish_sync(AgentMessage(team_id="team-y", from_agent="c"))

        team_x = bus.get_conversation("team-x")
        assert len(team_x) == 2
        team_y = bus.get_conversation("team-y")
        assert len(team_y) == 1

    def test_clear(self):
        bus = MessageBus()
        bus.publish_sync(AgentMessage(team_id="t1"))
        bus.clear()
        assert len(bus.get_conversation("t1")) == 0

    def test_handler_exception_does_not_crash(self):
        bus = MessageBus()
        received = []

        def bad_handler(msg):
            raise RuntimeError("boom")

        def good_handler(msg):
            received.append(msg)

        bus.subscribe("agent-1", bad_handler)
        bus.subscribe("agent-1", good_handler)

        bus.publish_sync(AgentMessage(to_agent="agent-1"))
        assert len(received) == 1  # good handler still fired

    def test_message_to_nonexistent_agent(self):
        bus = MessageBus()
        bus.publish_sync(AgentMessage(to_agent="nonexistent"))
        # Should not raise — silently ignored
