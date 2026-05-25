"""Tests for sandbox safe child path helper — bounty #3705."""

import os
import tempfile
from pathlib import Path

import pytest

from src.agent.sandbox import AgentSandbox


@pytest.fixture
def sandbox():
    sb = AgentSandbox()
    yield sb
    sb.cleanup_all()


@pytest.fixture
def agent_sandbox(sandbox):
    agent_id = "agent-test-1"
    sandbox.create(agent_id)
    return sandbox, agent_id


class TestSafeChildPath:
    def test_simple_child_path(self, agent_sandbox):
        sb, aid = agent_sandbox
        result = sb.safe_child_path(aid, "file.txt")
        expected = sb.get_path(aid) / "file.txt"
        assert result == expected

    def test_nested_child_path(self, agent_sandbox):
        sb, aid = agent_sandbox
        result = sb.safe_child_path(aid, "subdir/file.txt")
        expected = sb.get_path(aid) / "subdir" / "file.txt"
        assert result == expected

    def test_path_within_sandbox_resolves(self, agent_sandbox):
        sb, aid = agent_sandbox
        result = sb.safe_child_path(aid, "data/output.json")
        assert result.is_relative_to(sb.get_path(aid))

    def test_empty_child_path_returns_root(self, agent_sandbox):
        sb, aid = agent_sandbox
        result = sb.safe_child_path(aid, "")
        assert result == sb.get_path(aid)


class TestPathTraversalBlocked:
    def test_dotdot_traversal_blocked(self, agent_sandbox):
        sb, aid = agent_sandbox
        with pytest.raises(ValueError, match="path traversal"):
            sb.safe_child_path(aid, "../etc/passwd")

    def test_double_dotdot_traversal_blocked(self, agent_sandbox):
        sb, aid = agent_sandbox
        with pytest.raises(ValueError, match="path traversal"):
            sb.safe_child_path(aid, "../../root")

    def test_absolute_path_blocked(self, agent_sandbox):
        sb, aid = agent_sandbox
        with pytest.raises(ValueError, match="path traversal"):
            sb.safe_child_path(aid, "/etc/passwd")

    def test_traversal_within_path_blocked(self, agent_sandbox):
        sb, aid = agent_sandbox
        with pytest.raises(ValueError, match="path traversal"):
            sb.safe_child_path(aid, "foo/../../../etc/passwd")


class TestSafeChildEdgeCases:
    def test_missing_agent_raises(self, sandbox):
        with pytest.raises(ValueError, match="no sandbox"):
            sandbox.safe_child_path("nonexistent", "file.txt")

    def test_dot_entry_resolves_correctly(self, agent_sandbox):
        sb, aid = agent_sandbox
        result = sb.safe_child_path(aid, "./file.txt")
        assert result == sb.get_path(aid) / "file.txt"

    def test_multiple_agents_independent(self, sandbox):
        sandbox.create("agent-a")
        sandbox.create("agent-b")
        path_a = sandbox.safe_child_path("agent-a", "data.txt")
        path_b = sandbox.safe_child_path("agent-b", "data.txt")
        assert path_a != path_b

    def test_path_exists_after_create(self, agent_sandbox):
        sb, aid = agent_sandbox
        child = sb.safe_child_path(aid, "logs")
        child.mkdir()
        assert child.exists()
        assert child.is_dir()

    def test_windows_backslash_traversal_blocked(self, agent_sandbox):
        sb, aid = agent_sandbox
        with pytest.raises(ValueError, match="path traversal"):
            sb.safe_child_path(aid, "..\\..\\windows")
