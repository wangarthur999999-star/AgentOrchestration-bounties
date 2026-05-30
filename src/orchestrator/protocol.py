"""Agent-to-agent message protocol — typed messages and pub/sub routing."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4


class MessageType(Enum):
    TASK = "task"
    RESPONSE = "response"
    QUERY = "query"
    VOTE = "vote"
    BROADCAST = "broadcast"
    ERROR = "error"


@dataclass
class AgentMessage:
    """Standard message envelope for all agent communication."""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: MessageType = MessageType.TASK
    from_agent: str = ""
    to_agent: str = ""
    team_id: str = ""
    payload: dict = field(default_factory=dict)
    context_keys: list[str] = field(default_factory=list)
    reply_to: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class MessageBus:
    """In-process pub/sub message router — one per OrchestrationEngine."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = {}
        self._history: list[AgentMessage] = []
        self._lock = asyncio.Lock()

    async def publish(self, msg: AgentMessage) -> None:
        """Route a message to its target subscriber(s)."""
        self._history.append(msg)
        targets: list[str] = []

        if msg.to_agent == "BROADCAST":
            targets = list(self._subscribers.keys())
        elif msg.to_agent:
            targets = [msg.to_agent]

        for agent_id in targets:
            callbacks = self._subscribers.get(agent_id, [])
            for cb in callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(msg)
                    else:
                        cb(msg)
                except Exception:
                    import logging
                    _log = logging.getLogger(__name__)
                    _log.exception("MessageBus: callback %s failed for agent %s", cb, agent_id)

    def publish_sync(self, msg: AgentMessage) -> None:
        """Synchronous publish for non-async contexts."""
        self._history.append(msg)
        targets: list[str] = []

        if msg.to_agent == "BROADCAST":
            targets = list(self._subscribers.keys())
        elif msg.to_agent:
            targets = [msg.to_agent]

        for agent_id in targets:
            callbacks = self._subscribers.get(agent_id, [])
            for cb in callbacks:
                try:
                    cb(msg)
                except Exception:
                    import logging
                    _log = logging.getLogger(__name__)
                    _log.exception("MessageBus: callback %s failed for agent %s", cb, agent_id)

    def subscribe(self, agent_id: str, callback: Callable) -> None:
        """Register an agent to receive messages addressed to it."""
        if agent_id not in self._subscribers:
            self._subscribers[agent_id] = []
        self._subscribers[agent_id].append(callback)

    def unsubscribe(self, agent_id: str, callback: Callable) -> None:
        """Remove a subscription."""
        subs = self._subscribers.get(agent_id, [])
        if callback in subs:
            subs.remove(callback)

    def broadcast(self, msg: AgentMessage) -> AgentMessage:
        """Create and publish a broadcast message."""
        broadcast_msg = AgentMessage(
            type=MessageType.BROADCAST,
            from_agent=msg.from_agent,
            to_agent="BROADCAST",
            team_id=msg.team_id,
            payload=msg.payload,
            context_keys=msg.context_keys,
        )
        self.publish_sync(broadcast_msg)
        return broadcast_msg

    def get_conversation(self, team_id: str) -> list[AgentMessage]:
        """Return all messages for a given team conversation."""
        return [m for m in self._history if m.team_id == team_id]

    def clear(self) -> None:
        self._history.clear()
        self._subscribers.clear()
