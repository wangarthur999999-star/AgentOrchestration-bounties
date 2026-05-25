"""Tests for sandbox directory restrictive permissions — bounty #3788."""

import os
import stat
import sys

import pytest

from src.agent.sandbox import AgentSandbox, ResourceLimits

IS_WINDOWS = sys.platform == "win32"


class TestSandboxPermissions:
    def test_create_restrictive_permissions(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        sandbox_path = sb.create("agent-1")

        assert sandbox_path.exists()
        assert sandbox_path.is_dir()

        if not IS_WINDOWS:
            mode = sandbox_path.stat().st_mode
            perms = stat.S_IMODE(mode)
            assert perms == 0o700, f"Expected 0o700, got {oct(perms)}"

    def test_create_parents_with_restrictive_permissions(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path / "nested" / "dirs"))
        sandbox_path = sb.create("agent-2")

        assert sandbox_path.exists()

        if not IS_WINDOWS:
            perms = stat.S_IMODE(sandbox_path.stat().st_mode)
            assert perms == 0o700

    def test_existing_directory_preserved(self, tmp_path):
        sandbox_dir = tmp_path / "agent-3"
        sandbox_dir.mkdir(parents=True)

        sb = AgentSandbox(base_path=str(tmp_path))
        result = sb.create("agent-3")

        assert result == sandbox_dir
        assert result.exists()

    def test_permissions_not_world_readable(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        sandbox_path = sb.create("agent-4")

        if not IS_WINDOWS:
            mode = sandbox_path.stat().st_mode
            perms = stat.S_IMODE(mode)
            assert (perms & 0o077) == 0, f"Group/other bits set: {oct(perms)}"

    def test_creates_exclusive_agent_directories(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        path1 = sb.create("a")
        path2 = sb.create("b")

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_limits_none_does_not_affect_create(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        path = sb.create("agent-limits", limits=None)
        assert path.exists()


class TestDestroy:
    def test_destroy_removes_sandbox(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        sb.create("agent-del")
        assert sb.destroy("agent-del") is True
        assert not (tmp_path / "agent-del").exists()

    def test_destroy_unknown_returns_false(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        assert sb.destroy("nonexistent") is False

    def test_get_path_returns_none_after_destroy(self, tmp_path):
        sb = AgentSandbox(base_path=str(tmp_path))
        sb.create("agent-gone")
        sb.destroy("agent-gone")
        assert sb.get_path("agent-gone") is None


class TestResourceLimits:
    def test_default_limits(self):
        limits = ResourceLimits()
        assert limits.cpu_time == 60
        assert limits.memory_mb == 512
        assert limits.disk_mb == 100

    def test_custom_limits(self):
        limits = ResourceLimits(cpu_time=30, memory_mb=256, disk_mb=50)
        assert limits.cpu_time == 30
        assert limits.memory_mb == 256
        assert limits.disk_mb == 50
