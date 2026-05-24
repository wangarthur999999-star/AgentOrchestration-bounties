"""Tests for AgentSandbox — disk_mb enforcement and resource limits."""

import os
import tempfile
from pathlib import Path

import pytest

from src.agent.sandbox import AgentSandbox, QuotaExceededError, ResourceLimits


@pytest.fixture
def sandbox():
    sb = AgentSandbox()
    yield sb
    sb.cleanup_all()
    try:
        shutil = __import__("shutil")
        shutil.rmtree(sb.base_path, ignore_errors=True)
    except Exception:
        pass


class TestResourceLimits:
    def test_default_values(self):
        limits = ResourceLimits()
        assert limits.cpu_time == 60
        assert limits.memory_mb == 512
        assert limits.disk_mb == 100

    def test_custom_values(self):
        limits = ResourceLimits(cpu_time=30, memory_mb=256, disk_mb=50)
        assert limits.cpu_time == 30
        assert limits.memory_mb == 256
        assert limits.disk_mb == 50

    def test_disk_mb_none_disables_enforcement(self):
        limits = ResourceLimits(disk_mb=None)
        assert limits.disk_mb is None

    def test_repr(self):
        r = repr(ResourceLimits(cpu_time=10, memory_mb=20, disk_mb=30))
        assert "cpu_time=10" in r
        assert "memory_mb=20" in r
        assert "disk_mb=30" in r


class TestDiskQuotaEnforcement:
    def test_enforce_disk_mb_on_create(self, sandbox):
        limits = ResourceLimits(disk_mb=1)
        sandbox.create("agent1", limits=limits)
        # Write > 1MB of data
        filepath = sandbox.get_path("agent1") / "bigfile.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * (2 * 1024 * 1024))  # 2MB

        with pytest.raises(QuotaExceededError) as exc:
            sandbox.check_disk_quota("agent1")
        assert "disk quota exceeded" in str(exc.value)
        assert "agent1" in str(exc.value)

    def test_within_quota_passes(self, sandbox):
        limits = ResourceLimits(disk_mb=10)
        sandbox.create("agent2", limits=limits)
        filepath = sandbox.get_path("agent2") / "small.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * 1024)  # 1KB — well within 10MB

        sandbox.check_disk_quota("agent2")  # should not raise

    def test_disk_mb_none_skips_enforcement(self, sandbox):
        limits = ResourceLimits(disk_mb=None)
        sandbox.create("agent3", limits=limits)
        filepath = sandbox.get_path("agent3") / "big.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * (5 * 1024 * 1024))  # 5MB

        sandbox.check_disk_quota("agent3")  # no limit → no error

    def test_no_limits_provided(self, sandbox):
        sandbox.create("agent4")  # no limits at all
        filepath = sandbox.get_path("agent4") / "unlimited.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * (10 * 1024 * 1024))  # 10MB

        sandbox.check_disk_quota("agent4")  # no limits → no error

    def test_apply_limits_enforces_disk_quota(self, sandbox):
        sandbox.create("agent5")
        limits = ResourceLimits(disk_mb=1)
        sandbox.apply_limits("agent5", limits)

        # Write data exceeding the 1MB quota
        filepath = sandbox.get_path("agent5") / "exceed.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * (3 * 1024 * 1024))  # 3MB

        with pytest.raises(QuotaExceededError):
            sandbox.check_disk_quota("agent5")

    def test_get_disk_usage_empty_sandbox(self, sandbox):
        sandbox.create("agent6")
        usage = sandbox.get_disk_usage("agent6")
        assert usage == 0.0

    def test_get_disk_usage_returns_megabytes(self, sandbox):
        sandbox.create("agent7")
        filepath = sandbox.get_path("agent7") / "data.bin"
        with open(filepath, "wb") as f:
            f.write(b"\x00" * (2 * 1024 * 1024))  # 2MB

        usage = sandbox.get_disk_usage("agent7")
        assert 1.9 <= usage <= 2.1

    def test_get_disk_usage_nonexistent_agent(self, sandbox):
        usage = sandbox.get_disk_usage("nonexistent")
        assert usage == 0.0


class TestLimitStorage:
    def test_create_stores_limits(self, sandbox):
        limits = ResourceLimits(disk_mb=42)
        sandbox.create("agent8", limits=limits)
        stored = sandbox.get_limits("agent8")
        assert stored is not None
        assert stored.disk_mb == 42

    def test_get_limits_nonexistent(self, sandbox):
        assert sandbox.get_limits("nonexistent") is None

    def test_apply_limits_stores_and_overwrites(self, sandbox):
        sandbox.create("agent9")
        limits_a = ResourceLimits(disk_mb=10)
        sandbox.apply_limits("agent9", limits_a)
        assert sandbox.get_limits("agent9").disk_mb == 10

        limits_b = ResourceLimits(disk_mb=20)
        sandbox.apply_limits("agent9", limits_b)
        assert sandbox.get_limits("agent9").disk_mb == 20

    def test_destroy_clears_limits(self, sandbox):
        limits = ResourceLimits(disk_mb=5)
        sandbox.create("agent10", limits=limits)
        assert sandbox.get_limits("agent10") is not None
        sandbox.destroy("agent10")
        assert sandbox.get_limits("agent10") is None


class TestSandboxLifecycle:
    def test_create_returns_path(self, sandbox):
        path = sandbox.create("agent11")
        assert path.exists()
        assert path.is_dir()

    def test_destroy_removes_directory(self, sandbox):
        path = sandbox.create("agent12")
        assert sandbox.destroy("agent12")
        assert not path.exists()

    def test_destroy_returns_false_for_unknown_agent(self, sandbox):
        assert not sandbox.destroy("nonexistent")

    def test_get_path(self, sandbox):
        path = sandbox.create("agent13")
        retrieved = sandbox.get_path("agent13")
        assert retrieved == path

    def test_cleanup_all(self, sandbox):
        sandbox.create("agent14")
        sandbox.create("agent15")
        sandbox.cleanup_all()
        assert sandbox.get_path("agent14") is None
        assert sandbox.get_path("agent15") is None

    def test_disk_quota_respected_after_multiple_writes(self, sandbox):
        limits = ResourceLimits(disk_mb=2)
        sandbox.create("agent16", limits=limits)

        # Write 1MB — should be fine
        with open(sandbox.get_path("agent16") / "f1.bin", "wb") as f:
            f.write(b"\x00" * (1 * 1024 * 1024))
        sandbox.check_disk_quota("agent16")  # OK

        # Write another 1.5MB — should exceed 2MB limit
        with open(sandbox.get_path("agent16") / "f2.bin", "wb") as f:
            f.write(b"\x00" * (int(1.5 * 1024 * 1024)))

        with pytest.raises(QuotaExceededError):
            sandbox.check_disk_quota("agent16")


class TestQuotaExceededError:
    def test_is_exception(self):
        err = QuotaExceededError("test message")
        assert isinstance(err, Exception)

    def test_message_contains_details(self):
        err = QuotaExceededError("Sandbox 'x' disk quota exceeded: 5.00MB used, 1MB limit")
        assert "x" in str(err)
        assert "5.00MB" in str(err)
        assert "1MB" in str(err)
