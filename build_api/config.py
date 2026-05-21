from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int, minimum: int | None = None) -> int:
    try:
        result = int(value) if value is not None else default
    except ValueError:
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


@dataclass(frozen=True)
class Settings:
    project_root: Path
    base_briefcase_project: Path
    storage_dir: Path
    queue_file: Path
    workspaces_dir: Path
    artifacts_dir: Path
    uploads_dir: Path
    briefcase_command: tuple[str, ...]
    max_concurrent_builds: int
    build_timeout_seconds: int
    max_source_bytes: int
    max_image_bytes: int
    artifact_ttl_seconds: int
    cleanup_interval_seconds: int
    keep_workspaces: bool
    api_key: str | None

    @classmethod
    def load(cls) -> "Settings":
        dotenv = _read_dotenv(PROJECT_ROOT / ".env")
        env = {**dotenv, **os.environ}

        storage_dir = _resolve_path(env.get("BUILD_API_STORAGE_DIR", "build_api/runtime"), PROJECT_ROOT)
        briefcase_project = _resolve_path(env.get("BRIEFCASE_PROJECT_DIR", "api2app"), PROJECT_ROOT)

        command_value = env.get("BRIEFCASE_COMMAND", "venv/bin/briefcase")
        command = shlex.split(command_value)
        if not command:
            command = ["briefcase"]

        first = Path(command[0]).expanduser()
        if first.is_absolute():
            command[0] = str(first)
        elif "/" in command[0] or "\\" in command[0]:
            command[0] = str((PROJECT_ROOT / first).resolve())

        return cls(
            project_root=PROJECT_ROOT,
            base_briefcase_project=briefcase_project,
            storage_dir=storage_dir,
            queue_file=storage_dir / "queue.json",
            workspaces_dir=storage_dir / "workspaces",
            artifacts_dir=storage_dir / "artifacts",
            uploads_dir=storage_dir / "uploads",
            briefcase_command=tuple(command),
            max_concurrent_builds=_as_int(env.get("BUILD_MAX_CONCURRENT"), default=1, minimum=1),
            build_timeout_seconds=_as_int(env.get("BUILD_TIMEOUT_SECONDS"), default=7200, minimum=60),
            max_source_bytes=_as_int(env.get("MAX_SOURCE_BYTES"), default=5_000_000, minimum=1024),
            max_image_bytes=_as_int(env.get("MAX_IMAGE_BYTES"), default=10_000_000, minimum=1024),
            artifact_ttl_seconds=_as_int(env.get("ARTIFACT_TTL_SECONDS"), default=3600, minimum=60),
            cleanup_interval_seconds=_as_int(env.get("CLEANUP_INTERVAL_SECONDS"), default=300, minimum=10),
            keep_workspaces=_as_bool(env.get("BUILD_KEEP_WORKSPACES"), default=False),
            api_key=(env.get("BUILD_API_KEY") or "").strip() or None,
        )

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
