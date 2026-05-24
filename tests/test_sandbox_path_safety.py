"""Tests for agent_id sanitization — prevents path traversal in sandbox."""

import pytest

from src.agent.sandbox import AgentSandbox


@pytest.fixture
def sandbox():
    sb = AgentSandbox()
    yield sb
    sb.cleanup_all()
    try:
        import shutil
        shutil.rmtree(sb.base_path, ignore_errors=True)
    except Exception:
        pass


class TestAgentIdSanitization:
    def test_valid_agent_id_accepted(self, sandbox):
        path = sandbox.create("my-agent_01-v2")
        assert path.exists()

    def test_empty_agent_id_rejected(self, sandbox):
        with pytest.raises(ValueError, match="must not be empty"):
            sandbox.create("")

    def test_whitespace_only_rejected(self, sandbox):
        with pytest.raises(ValueError, match="must not be empty"):
            sandbox.create("   ")

    def test_dot_dot_path_traversal_rejected(self, sandbox):
        with pytest.raises(ValueError, match="path traversal"):
            sandbox.create("../../etc/passwd")

    def test_forward_slash_rejected(self, sandbox):
        with pytest.raises(ValueError, match="path separator"):
            sandbox.create("agent/subdir")

    def test_backslash_rejected(self, sandbox):
        with pytest.raises(ValueError, match="path separator"):
            sandbox.create("agent\\windows")

    def test_null_byte_rejected(self, sandbox):
        with pytest.raises(ValueError, match="invalid characters"):
            sandbox.create("agent\x00bad")

    def test_semicolon_rejected(self, sandbox):
        with pytest.raises(ValueError, match="invalid characters"):
            sandbox.create("agent;cmd")

    def test_pipe_rejected(self, sandbox):
        with pytest.raises(ValueError, match="invalid characters"):
            sandbox.create("agent|shell")

    def test_hyphen_underscore_dot_accepted(self, sandbox):
        path = sandbox.create("my-agent_v2.0-test")
        assert path.exists()
        assert path.name == "my-agent_v2.0-test"

    def test_single_dot_not_rejected(self, sandbox):
        path = sandbox.create("agent.v1.0")
        assert path.exists()


class TestPathSafetyWithExistingSandboxes:
    def test_sanitize_called_on_every_create(self, sandbox):
        sandbox.create("safe-agent")
        sandbox.create("other.agent_2")

        with pytest.raises(ValueError, match="path traversal"):
            sandbox.create("../../../escape")

        # Previous sandboxes still exist
        assert sandbox.get_path("safe-agent") is not None
        assert sandbox.get_path("other.agent_2") is not None

    def test_destroy_still_works_after_rejected_create(self, sandbox):
        sandbox.create("valid-agent")
        with pytest.raises(ValueError):
            sandbox.create("../escape")
        assert sandbox.destroy("valid-agent")
