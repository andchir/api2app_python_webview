from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class QueueStore:
    def __init__(self, queue_file: Path):
        self.queue_file = queue_file
        self._lock = threading.RLock()

    def ensure(self) -> None:
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_file.exists():
            self._write({"jobs": []})

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read()
            return sorted(data["jobs"], key=lambda job: job.get("created_at", ""))

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            for job in self._read()["jobs"]:
                if job.get("job_id") == job_id:
                    return dict(job)
        return None

    def upsert(self, job: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            jobs = [existing for existing in data["jobs"] if existing.get("job_id") != job["job_id"]]
            jobs.append(job)
            data["jobs"] = sorted(jobs, key=lambda item: item.get("created_at", ""))
            self._write(data)

    def remove(self, job_id: str) -> None:
        with self._lock:
            data = self._read()
            data["jobs"] = [job for job in data["jobs"] if job.get("job_id") != job_id]
            self._write(data)

    def position(self, job_id: str) -> int | None:
        queued = [job for job in self.list_jobs() if job.get("status") == "queued"]
        for index, job in enumerate(queued, start=1):
            if job.get("job_id") == job_id:
                return index
        return None

    def _read(self) -> dict[str, Any]:
        if not self.queue_file.exists():
            return {"jobs": []}
        data = json.loads(self.queue_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return {"jobs": []}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.queue_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_file.replace(self.queue_file)

