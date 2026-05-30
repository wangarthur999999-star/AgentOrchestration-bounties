"""Shared Blackboard — team-scoped key-value store for agent collaboration."""

import asyncio
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BlackboardEntry:
    key: str
    value: Any
    version: int = 1
    created_by: str = ""
    timestamp: float = field(default_factory=time.time)
    ttl: Optional[float] = None


class SharedBlackboard:
    """Team-scoped key-value store enabling agents to share intermediate results.

    Agents write results to the blackboard and read others' outputs without
    direct coupling. Supports optimistic concurrency via compare_and_swap
    and async waiting via watch().
    """

    def __init__(self, team_id: str) -> None:
        self.team_id = team_id
        self._store: dict[str, BlackboardEntry] = {}
        self._events: dict[str, asyncio.Event] = {}

    def put(
        self, key: str, value: Any, agent_id: str, ttl: Optional[float] = None
    ) -> BlackboardEntry:
        """Write a value to the blackboard, incrementing the version."""
        existing = self._store.get(key)
        version = (existing.version + 1) if existing else 1
        entry = BlackboardEntry(
            key=key, value=copy.deepcopy(value), version=version,
            created_by=agent_id, ttl=ttl,
        )
        self._store[key] = entry

        event = self._events.get(key)
        if event:
            event.set()

        return entry

    def get(self, key: str) -> Optional[Any]:
        """Read a value, checking TTL expiry first."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.ttl and (time.time() - entry.timestamp) > entry.ttl:
            del self._store[key]
            return None
        return copy.deepcopy(entry.value)

    def get_entry(self, key: str) -> Optional[BlackboardEntry]:
        """Read the full entry with metadata (version, creator, etc.)."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.ttl and (time.time() - entry.timestamp) > entry.ttl:
            del self._store[key]
            return None
        return entry

    def get_all(self, prefix: str = "") -> dict[str, Any]:
        """Read all keys matching a prefix. Empty prefix returns all."""
        result = {}
        for key in list(self._store.keys()):
            if key.startswith(prefix):
                val = self.get(key)
                if val is not None:
                    result[key] = val
        return result

    def compare_and_swap(
        self, key: str, expected_version: int, new_value: Any, agent_id: str
    ) -> bool:
        """Atomically update a value only if the version hasn't changed."""
        entry = self._store.get(key)
        if entry is None or entry.version != expected_version:
            return False
        entry.value = copy.deepcopy(new_value)
        entry.version = expected_version + 1
        entry.created_by = agent_id
        entry.timestamp = time.time()
        event = self._events.get(key)
        if event:
            event.set()
        return True

    async def watch(self, key: str, timeout: float = 30.0) -> Any:
        """Wait for a key to be written, then return its value."""
        existing = self.get(key)
        if existing is not None:
            return existing

        if key not in self._events:
            self._events[key] = asyncio.Event()
        else:
            self._events[key].clear()

        try:
            await asyncio.wait_for(self._events[key].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        return self.get(key)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of all current (non-expired) entries."""
        return self.get_all()

    def delete(self, key: str) -> bool:
        """Remove a key from the blackboard."""
        existed = key in self._store
        self._store.pop(key, None)
        self._events.pop(key, None)
        return existed

    def clear(self) -> None:
        """Remove all entries and event watchers."""
        self._store.clear()
        for event in self._events.values():
            event.set()
        self._events.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        return key in self._store
