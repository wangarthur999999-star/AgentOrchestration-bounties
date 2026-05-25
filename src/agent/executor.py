"""Agent Executor — Handles task execution within agent sandboxes."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


class AgentExecutor:
    def __init__(self, max_concurrent: int = 5, max_results: int = 1000, grace_period: float = 3600.0):
        self.max_concurrent = max_concurrent
        self.max_results = max_results
        self.grace_period = grace_period
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._result_timestamps: Dict[str, float] = {}

    async def execute(self, agent_id: str, task: Dict[str, Any], handler: Callable) -> str:
        execution_id = str(uuid4())
        async with self._semaphore:
            task_obj = asyncio.create_task(
                self._run_execution(execution_id, agent_id, task, handler)
            )
            self._active_tasks[execution_id] = task_obj
            try:
                result = await task_obj
                self._store_result(execution_id, result)
            except Exception as e:
                self._store_result(execution_id, {"error": str(e)})
            finally:
                self._active_tasks.pop(execution_id, None)
        return execution_id

    def _store_result(self, execution_id: str, result: Any) -> None:
        self._results[execution_id] = result
        self._result_timestamps[execution_id] = time.time()
        if len(self._results) > self.max_results:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        if not self._result_timestamps:
            return
        oldest_id = min(self._result_timestamps, key=self._result_timestamps.get)
        self._results.pop(oldest_id, None)
        self._result_timestamps.pop(oldest_id, None)

    async def _run_execution(self, exec_id: str, agent_id: str, task: Dict, handler: Callable) -> Any:
        start = time.time()
        result = await handler(agent_id, task)
        duration = time.time() - start
        return {
            "execution_id": exec_id,
            "agent_id": agent_id,
            "task_id": task.get("id"),
            "result": result,
            "duration": duration,
            "timestamp": time.time(),
        }

    def get_result(self, execution_id: str) -> Optional[Any]:
        return self._results.get(execution_id)

    def cancel(self, execution_id: str) -> bool:
        task = self._active_tasks.get(execution_id)
        if task and not task.done():
            task.cancel()
            self._results.pop(execution_id, None)
            self._result_timestamps.pop(execution_id, None)
            return True
        return False

    def cleanup_orphaned(self) -> Dict[str, int]:
        now = time.time()
        orphaned_ids = [
            eid for eid, ts in self._result_timestamps.items()
            if now - ts > self.grace_period
        ]
        deleted_bytes = 0
        for eid in orphaned_ids:
            result = self._results.pop(eid, None)
            if result is not None:
                deleted_bytes += len(str(result))
            self._result_timestamps.pop(eid, None)
        return {"orphaned_count": len(orphaned_ids), "deleted_bytes": deleted_bytes}

    def result_count(self) -> int:
        return len(self._results)

    async def shutdown(self) -> None:
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
