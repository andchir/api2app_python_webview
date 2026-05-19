from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .builder import artifact_path, delete_result, is_result_expired, load_result, log_path
from .config import Settings
from .schemas import (
    ActiveJobsResponse,
    AndroidBuildRequest,
    BuildAccepted,
    JobStatusResponse,
    WindowsBuildRequest,
    model_to_dict,
)
from .worker import BuildQueue


settings = Settings.load()
build_queue = BuildQueue(settings)

app = FastAPI(
    title="api2app Build API",
    version="0.1.0",
    description="Build Android APK and Windows MSI/EXE packages from submitted HTML/CSS/JS code.",
)


@app.on_event("startup")
async def startup() -> None:
    await build_queue.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await build_queue.stop()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "max_concurrent_builds": settings.max_concurrent_builds,
        "queue_file": str(settings.queue_file),
    }


@app.post("/build/android", response_model=BuildAccepted, status_code=202)
async def build_android(payload: AndroidBuildRequest, request: Request) -> BuildAccepted:
    job = await _enqueue_or_413("android", model_to_dict(payload), None)
    return _accepted_response(job["job_id"], request)


@app.post("/build/windows", response_model=BuildAccepted, status_code=202)
async def build_windows(payload: WindowsBuildRequest, request: Request) -> BuildAccepted:
    body = model_to_dict(payload)
    package_format = body.pop("package_format")
    job = await _enqueue_or_413("windows", body, package_format)
    return _accepted_response(job["job_id"], request)


@app.get("/jobs", response_model=ActiveJobsResponse)
async def list_jobs(request: Request) -> ActiveJobsResponse:
    jobs = [_status_response(status, request) for status in build_queue.list_active() if status]
    return ActiveJobsResponse(jobs=jobs)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    status = build_queue.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return _status_response(status, request)


@app.get("/jobs/{job_id}/download")
async def download_artifact(job_id: str) -> FileResponse:
    result = load_result(job_id, settings)
    if not result:
        raise HTTPException(status_code=404, detail="Job not found or not finished yet")
    if is_result_expired(result):
        delete_result(job_id, settings)
        raise HTTPException(status_code=404, detail="Job result expired")
    if result.get("status") != "completed":
        raise HTTPException(status_code=409, detail=result.get("message", "Build is not completed"))

    path = artifact_path(job_id, settings)
    if not path:
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return FileResponse(
        path,
        filename=path.name,
        media_type=_artifact_media_type(path),
    )


@app.get("/jobs/{job_id}/log")
async def download_log(job_id: str) -> FileResponse:
    result = load_result(job_id, settings)
    if result and is_result_expired(result):
        delete_result(job_id, settings)
        raise HTTPException(status_code=404, detail="Job result expired")
    path = log_path(job_id, settings)
    if not path:
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(path, filename=f"{job_id}.log", media_type="text/plain")


async def _enqueue_or_413(target: str, payload: dict, package_format: str | None) -> dict:
    try:
        return await build_queue.enqueue(target, payload, package_format)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


def _accepted_response(job_id: str, request: Request) -> BuildAccepted:
    return BuildAccepted(
        job_id=job_id,
        status="queued",
        status_url=str(request.url_for("get_job_status", job_id=job_id)),
        download_url=str(request.url_for("download_artifact", job_id=job_id)),
        log_url=str(request.url_for("download_log", job_id=job_id)),
    )


def _status_response(status: dict, request: Request) -> JobStatusResponse:
    job_id = status["job_id"]
    payload = dict(status)
    payload["status_url"] = str(request.url_for("get_job_status", job_id=job_id))
    payload["log_url"] = str(request.url_for("download_log", job_id=job_id))
    if status.get("status") == "completed":
        payload["download_url"] = str(request.url_for("download_artifact", job_id=job_id))
    return JobStatusResponse(**payload)


def _artifact_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".apk":
        return "application/vnd.android.package-archive"
    if suffix == ".msi":
        return "application/x-msi"
    if suffix == ".exe":
        return "application/vnd.microsoft.portable-executable"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"
