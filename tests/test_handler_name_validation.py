"""Tests for handler name path traversal prevention in AgentRegistry."""

import pytest

from src.agent.registry import AgentRegistry


@pytest.fixture
def registry():
    return AgentRegistry()


class TestValidHandlerNames:
    def test_accepts_simple_name(self, registry):
        agent_id = registry.register("my-agent", "worker.default")
        assert agent_id is not None

    def test_accepts_dotted_name(self, registry):
        agent_id = registry.register("com.example.agent", "worker.default")
        assert agent_id is not None

    def test_accepts_alphanumeric(self, registry):
        agent_id = registry.register("AgentV2", "worker.default")
        assert agent_id is not None

    def test_accepts_underscore(self, registry):
        agent_id = registry.register("my_agent_handler", "worker.default")
        assert agent_id is not None

    def test_accepts_hyphen(self, registry):
        agent_id = registry.register("my-agent-handler", "worker.default")
        assert agent_id is not None


class TestPathTraversalRejection:
    def test_rejects_empty_name(self, registry):
        with pytest.raises(ValueError, match="empty"):
            registry.register("", "worker.default")

    def test_rejects_whitespace_name(self, registry):
        with pytest.raises(ValueError, match="empty"):
            registry.register("   ", "worker.default")

    def test_rejects_dot_dot(self, registry):
        with pytest.raises(ValueError, match="path traversal"):
            registry.register("../etc/passwd", "worker.default")

    def test_rejects_forward_slash(self, registry):
        with pytest.raises(ValueError, match="path separator"):
            registry.register("agent/name", "worker.default")

    def test_rejects_backslash(self, registry):
        with pytest.raises(ValueError, match="path separator"):
            registry.register("agent\\name", "worker.default")

    def test_rejects_null_byte(self, registry):
        with pytest.raises(ValueError, match="invalid characters"):
            registry.register("agent\x00name", "worker.default")

    def test_rejects_semicolon(self, registry):
        with pytest.raises(ValueError, match="invalid characters"):
            registry.register("agent;cmd", "worker.default")

    def test_rejects_pipe(self, registry):
        with pytest.raises(ValueError, match="invalid characters"):
            registry.register("agent|cmd", "worker.default")


class TestValidationStateIntegrity:
    def test_invalid_name_does_not_leak(self, registry):
        try:
            registry.register("bad/name", "worker.default")
        except ValueError:
            pass
        assert registry.count() == 0
        assert registry.list() == []

    def test_valid_after_invalid(self, registry):
        try:
            registry.register("bad/name", "worker.default")
        except ValueError:
            pass
        agent_id = registry.register("clean-name", "worker.default")
        assert agent_id is not None
        assert registry.count() == 1

    def test_name_preserved_in_registry(self, registry):
        agent_id = registry.register("test-handler", "worker.default")
        agent = registry.get(agent_id)
        assert agent["name"] == "test-handler"
