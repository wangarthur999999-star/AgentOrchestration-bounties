"""Agent Sandbox — Isolated execution environment for agents."""

import os
import shutil
import tempfile
from typing import Any, Dict, Optional

try:
    import resource
except ImportError:
    resource = None  # Windows: no resource module
from pathlib import Path


class QuotaExceededError(Exception):
    """Raised when a sandbox exceeds its disk quota."""


class ResourceLimits:
    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: Optional[int] = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb

    def __repr__(self) -> str:
        return (f"ResourceLimits(cpu_time={self.cpu_time}, "
                f"memory_mb={self.memory_mb}, disk_mb={self.disk_mb})")


class AgentSandbox:
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or tempfile.mkdtemp(prefix="ao_sandbox_"))
        self._sandboxes: Dict[str, Path] = {}
        self._limits: Dict[str, ResourceLimits] = {}

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        sandbox_path = self.base_path / agent_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[agent_id] = sandbox_path
        if limits is not None:
            self._limits[agent_id] = limits
            self._validate_disk_quota(agent_id)
        return sandbox_path

    def destroy(self, agent_id: str) -> bool:
        sandbox = self._sandboxes.pop(agent_id, None)
        self._limits.pop(agent_id, None)
        if sandbox and sandbox.exists():
            shutil.rmtree(sandbox, ignore_errors=True)
            return True
        return False

    def get_path(self, agent_id: str) -> Optional[Path]:
        return self._sandboxes.get(agent_id)

    def get_limits(self, agent_id: str) -> Optional[ResourceLimits]:
        return self._limits.get(agent_id)

    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> None:
        self._limits[agent_id] = limits

        if resource is not None:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time, limits.cpu_time))
                mem_bytes = limits.memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, resource.error):
                pass

        self._validate_disk_quota(agent_id)

    def check_disk_quota(self, agent_id: str) -> None:
        """Verify the sandbox is within its disk limit. Call before/after file writes."""
        self._validate_disk_quota(agent_id)

    def get_disk_usage(self, agent_id: str) -> float:
        """Return current sandbox disk usage in MB."""
        sandbox_path = self._sandboxes.get(agent_id)
        if sandbox_path is None or not sandbox_path.exists():
            return 0.0
        total = sum(
            f.stat().st_size for f in sandbox_path.rglob("*") if f.is_file()
        )
        return total / (1024 * 1024)

    def _validate_disk_quota(self, agent_id: str) -> None:
        limits = self._limits.get(agent_id)
        if limits is None or limits.disk_mb is None:
            return
        usage_mb = self.get_disk_usage(agent_id)
        if usage_mb > limits.disk_mb:
            raise QuotaExceededError(
                f"Sandbox '{agent_id}' disk quota exceeded: "
                f"{usage_mb:.2f}MB used, {limits.disk_mb}MB limit"
            )

    def cleanup_all(self) -> None:
        for agent_id in list(self._sandboxes.keys()):
            self.destroy(agent_id)
