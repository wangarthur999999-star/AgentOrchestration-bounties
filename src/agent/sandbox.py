"""Agent Sandbox — Isolated execution environment for agents."""

import os
import re
import tempfile
from typing import Dict, Optional

try:
    import resource
except ImportError:
    resource = None  # Windows: no resource module
from pathlib import Path

_SAFE_AGENT_ID = re.compile(r'^[a-zA-Z0-9._\-]+$')


class ResourceLimits:
    def __init__(self, cpu_time: int = 60, memory_mb: int = 512, disk_mb: int = 100):
        self.cpu_time = cpu_time
        self.memory_mb = memory_mb
        self.disk_mb = disk_mb


class AgentSandbox:
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or tempfile.mkdtemp(prefix="ao_sandbox_"))
        self._sandboxes: Dict[str, Path] = {}

    @staticmethod
    def _sanitize_agent_id(agent_id: str) -> str:
        if not agent_id or not agent_id.strip():
            raise ValueError(f"agent_id must not be empty")
        if ".." in agent_id:
            raise ValueError(f"agent_id contains path traversal: {agent_id!r}")
        if "/" in agent_id or "\\" in agent_id:
            raise ValueError(f"agent_id contains path separator: {agent_id!r}")
        if not _SAFE_AGENT_ID.match(agent_id):
            raise ValueError(
                f"agent_id contains invalid characters: {agent_id!r}. "
                f"Allowed: alphanumeric, ., _, -"
            )
        return agent_id

    def create(self, agent_id: str, limits: Optional[ResourceLimits] = None) -> Path:
        self._sanitize_agent_id(agent_id)
        sandbox_path = self.base_path / agent_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        self._sandboxes[agent_id] = sandbox_path
        return sandbox_path

    def destroy(self, agent_id: str) -> bool:
        sandbox = self._sandboxes.pop(agent_id, None)
        if sandbox and sandbox.exists():
            import shutil
            shutil.rmtree(sandbox, ignore_errors=True)
            return True
        return False

    def get_path(self, agent_id: str) -> Optional[Path]:
        return self._sandboxes.get(agent_id)

    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> None:
        if resource is None:
            return  # Windows: resource limits not supported
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time, limits.cpu_time))
            mem_bytes = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, resource.error) as e:
            pass

    def cleanup_all(self) -> None:
        for agent_id in list(self._sandboxes.keys()):
            self.destroy(agent_id)
