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
    def __init__(self, max_retries: int = 3):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = max_retries
        self._capacity: Dict[str, int] = {}
        self._usage: Dict[str, int] = {}

    def set_capacity(self, queue: str, max_capacity: int) -> None:
        self._capacity[queue] = max_capacity
        if queue not in self._usage:
            self._usage[queue] = 0

    def get_capacity(self, queue: str) -> Optional[int]:
        return self._capacity.get(queue)

    def get_usage(self, queue: str) -> int:
        return self._usage.get(queue, 0)

    def release_capacity(self, queue: str, count: int = 1) -> int:
        if queue not in self._usage:
            self._usage[queue] = 0
        released = min(count, self._usage[queue])
        self._usage[queue] -= released
        return released

    def _reserve_capacity(self, queue: str) -> bool:
        max_cap = self._capacity.get(queue)
        if max_cap is None:
            return True
        if queue not in self._usage:
            self._usage[queue] = 0
        if self._usage[queue] < max_cap:
            self._usage[queue] += 1
            return True
        return False

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        if not self._reserve_capacity(queue):
            raise RuntimeError(f"Queue '{queue}' at capacity ({self._capacity[queue]})")

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        try:
            if queue not in self._queues:
                self._queues[queue] = PriorityQueue()
            self._queues[queue].push(task, priority)
            return task_id
        except Exception:
            self.release_capacity(queue)
            raise

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
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            self.release_capacity(task.get("queue", "default"))
        return task is not None

    def _enqueue_internal(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task["id"]

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self._enqueue_internal(task, queue, priority=task.get("priority", 0))
                return True
            else:
                self.release_capacity(queue)
        return False

    def queue_size(self, queue: str = "default") -> int:
        if queue in self._queues:
            return len(self._queues[queue])
        return 0
