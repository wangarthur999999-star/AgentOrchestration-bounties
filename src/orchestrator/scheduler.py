"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self, max_retries: int = 3, reservation_ttl: float = 300.0):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = max_retries
        self._reservation_ttl = reservation_ttl
        self._reserved_at: Dict[str, float] = {}

    def set_reservation_ttl(self, ttl: float) -> None:
        self._reservation_ttl = ttl

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            self._scheduled.pop(tid, None)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                self._reserved_at[task["id"]] = now
                return task
        return None

    def complete(self, task_id: str) -> bool:
        self._reserved_at.pop(task_id, None)
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        self._reserved_at.pop(task_id, None)
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def reclaim_abandoned(self, ttl: Optional[float] = None) -> Dict[str, int]:
        ttl = ttl if ttl is not None else self._reservation_ttl
        now = time.time()
        reclaimed = 0
        re_enqueued = 0

        abandoned_ids = [
            tid for tid, ts in self._reserved_at.items()
            if now - ts > ttl
        ]

        for task_id in abandoned_ids:
            task = self._in_flight.pop(task_id, None)
            self._reserved_at.pop(task_id, None)
            if task:
                reclaimed += 1
                self.enqueue(task, queue=task.get("queue", "default"), priority=task.get("priority", 0))
                re_enqueued += 1

        return {"abandoned": reclaimed, "re_enqueued": re_enqueued}

    def queue_size(self, queue: str = "default") -> int:
        if queue in self._queues:
            return len(self._queues[queue])
        return 0
