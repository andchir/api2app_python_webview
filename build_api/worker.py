from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from .builder import (
    cleanup_expired_results,
    cleanup_workspaces,
    delete_result,
    is_result_expired,
    load_result,
    run_build,
    utc_now,
    write_result,
)
from .config import Settings
from .queue_store import QueueStore


class BuildQueue:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = QueueStore(settings.queue_file)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._cleanup_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self.settings.ensure_directories()
        self.store.ensure()
        cleanup_workspaces(self.settings)
        cleanup_expired_results(self.settings)

        for job in self.store.list_jobs():
            if job.get("status") in {"queued", "running"}:
                job["status"] = "queued"
                job["started_at"] = None
                job["updated_at"] = utc_now()
                self.store.upsert(job)
                await self.queue.put(job["job_id"])

        self._workers = [
            asyncio.create_task(self._worker_loop(), name=f"build-worker-{index}")
            for index in range(self.settings.max_concurrent_builds)
        ]
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="build-cleanup")
        self._started = True

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        self._workers = []
        self._started = False

    async def enqueue(self, target: str, request: dict[str, Any], package_format: str | None = None) -> dict[str, Any]:
        self._validate_source_size(request)
        now = utc_now()
        job = {
            "job_id": uuid.uuid4().hex,
            "target": target,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "request": request,
            "package_format": package_format,
        }
        self.store.upsert(job)
        await self.queue.put(job["job_id"])
        return job

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        active = self.store.get(job_id)
        if active:
            status = {
                "job_id": active["job_id"],
                "target": active["target"],
                "status": active["status"],
                "created_at": active["created_at"],
                "updated_at": active.get("updated_at"),
                "started_at": active.get("started_at"),
                "position": self.store.position(job_id) if active.get("status") == "queued" else None,
                "message": active.get("message"),
            }
            return status

        result = load_result(job_id, self.settings)
        if result and is_result_expired(result):
            delete_result(job_id, self.settings)
            return None
        return result

    def list_active(self) -> list[dict[str, Any]]:
        return [self.get_status(job["job_id"]) for job in self.store.list_jobs()]

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                job = self.store.get(job_id)
                if not job:
                    continue

                now = utc_now()
                job["status"] = "running"
                job["started_at"] = now
                job["updated_at"] = now
                self.store.upsert(job)

                result = await run_build(job, self.settings)
                write_result(result, self.settings)
                self.store.remove(job_id)
            finally:
                self.queue.task_done()

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.cleanup_interval_seconds)
            cleanup_expired_results(self.settings)

    def _validate_source_size(self, request: dict[str, Any]) -> None:
        total = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        if total > self.settings.max_source_bytes:
            raise ValueError(
                f"Source payload is too large: {total} bytes, limit is {self.settings.max_source_bytes} bytes"
            )
