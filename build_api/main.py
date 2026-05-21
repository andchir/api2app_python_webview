from __future__ import annotations

import hmac
import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError
from starlette.datastructures import UploadFile

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

IMAGE_CHUNK_SIZE = 1024 * 1024
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ico"}
TRUE_FORM_VALUES = {"1", "true", "yes", "on"}
FALSE_FORM_VALUES = {"0", "false", "no", "off"}
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

COMMON_FORM_PROPERTIES: dict[str, Any] = {
    "html": {
        "type": "string",
        "format": "textarea",
        "description": "Full HTML document.",
    },
    "css": {
        "type": "string",
        "format": "textarea",
        "default": "",
    },
    "js": {
        "type": "string",
        "format": "textarea",
        "default": "",
    },
    "app_name": {"type": "string", "default": "api2app generated"},
    "bundle": {"type": "string", "default": "com.api2app.generated"},
    "version": {"type": "string", "default": "0.0.1"},
    "description": {"type": "string", "default": "Generated WebView application"},
    "header_enabled": {"type": "boolean"},
    "header_title": {"type": "string"},
    "header_subtitle": {"type": "string"},
    "header_background_color": {"type": "string", "default": "#111827"},
    "header_text_color": {"type": "string", "default": "#ffffff"},
    "menu_enabled": {"type": "boolean"},
    "menu_position": {"type": "string", "enum": ["top", "bottom"], "default": "top"},
    "menu_background_color": {"type": "string", "default": "#f8fafc"},
    "menu_text_color": {"type": "string", "default": "#111827"},
    "menu_items": {
        "type": "string",
        "description": 'JSON array of menu items, e.g. [{"label":"Home","href":"#home"}]',
    },
    "icon_file": {"type": "string", "format": "binary"},
    "icon_url": {"type": "string", "format": "uri"},
    "ico_file": {"type": "string", "format": "binary"},
    "ico_url": {"type": "string", "format": "uri"},
}


def _form_openapi_extra(*, include_windows_format: bool = False) -> dict[str, Any]:
    properties = dict(COMMON_FORM_PROPERTIES)
    if include_windows_format:
        properties["package_format"] = {
            "type": "string",
            "enum": ["msi", "zip", "exe"],
            "default": "msi",
        }

    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["html"],
                        "properties": properties,
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["html"],
                        "properties": properties,
                    }
                },
            },
        }
    }


def _swagger_textarea_script() -> str:
    return """
<script>
(function () {
  const fields = new Set(["html", "css", "js"]);
  let timer = null;

  function fieldName(row) {
    const nameCell = row.querySelector(".parameters-col_name") || row.querySelector("td:first-child");
    if (!nameCell) {
      return null;
    }
    const text = nameCell.textContent.trim();
    for (const field of fields) {
      if (new RegExp("^" + field + "\\\\b").test(text)) {
        return field;
      }
    }
    return null;
  }

  function setNativeValue(element, value) {
    const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;

    if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else if (valueSetter) {
      valueSetter.call(element, value);
    } else {
      element.value = value;
    }
  }

  function syncInput(input, value) {
    setNativeValue(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function enhance() {
    document.querySelectorAll("tr").forEach((row) => {
      const name = fieldName(row);
      if (!name || row.querySelector("textarea[data-api2app-textarea-for='" + name + "']")) {
        return;
      }

      const input = row.querySelector("input[type='text'], input:not([type])");
      if (!input || input.dataset.api2appTextareaSource === "true") {
        return;
      }

      const textarea = document.createElement("textarea");
      textarea.dataset.api2appTextareaFor = name;
      textarea.className = input.className;
      textarea.placeholder = input.placeholder || name;
      textarea.value = input.value || "";
      textarea.setAttribute("aria-label", input.getAttribute("aria-label") || name);
      textarea.style.boxSizing = "border-box";
      textarea.style.fontFamily = "monospace";
      textarea.style.minHeight = name === "html" ? "260px" : "160px";
      textarea.style.resize = "vertical";
      textarea.style.width = "100%";

      input.dataset.api2appTextareaSource = "true";
      input.style.display = "none";
      input.insertAdjacentElement("afterend", textarea);

      textarea.addEventListener("input", () => syncInput(input, textarea.value));
      textarea.addEventListener("change", () => syncInput(input, textarea.value));
      syncInput(input, textarea.value);
    });
  }

  function scheduleEnhance() {
    window.clearTimeout(timer);
    timer = window.setTimeout(enhance, 50);
  }

  window.addEventListener("load", scheduleEnhance);
  new MutationObserver(scheduleEnhance).observe(document.body, { childList: true, subtree: true });
})();
</script>
""".strip()


app = FastAPI(
    title="api2app Build API",
    version="0.1.0",
    description="Build Android APK and Windows MSI/EXE packages from submitted HTML/CSS/JS code.",
    docs_url=None,
)


@app.on_event("startup")
async def startup() -> None:
    await build_queue.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await build_queue.stop()


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html() -> HTMLResponse:
    response = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
    )
    html = response.body.decode("utf-8")
    html = html.replace("</body>", f"{_swagger_textarea_script()}\n</body>")
    return HTMLResponse(html)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "max_concurrent_builds": settings.max_concurrent_builds,
        "queue_file": str(settings.queue_file),
        "max_image_bytes": settings.max_image_bytes,
    }


async def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=500, detail="BUILD_API_KEY is not configured")
    if api_key is None or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.post(
    "/build/android",
    response_model=BuildAccepted,
    status_code=202,
    openapi_extra=_form_openapi_extra(),
    dependencies=[Depends(require_api_key)],
)
async def build_android(request: Request) -> BuildAccepted:
    payload, assets_dir = await _payload_from_form(request, AndroidBuildRequest)
    try:
        job = await _enqueue_or_413("android", payload, None)
    except Exception:
        _cleanup_asset_dir(assets_dir)
        raise
    return _accepted_response(job["job_id"], request)


@app.post(
    "/build/windows",
    response_model=BuildAccepted,
    status_code=202,
    openapi_extra=_form_openapi_extra(include_windows_format=True),
    dependencies=[Depends(require_api_key)],
)
async def build_windows(request: Request) -> BuildAccepted:
    body, assets_dir = await _payload_from_form(request, WindowsBuildRequest)
    package_format = body.pop("package_format")
    try:
        job = await _enqueue_or_413("windows", body, package_format)
    except Exception:
        _cleanup_asset_dir(assets_dir)
        raise
    return _accepted_response(job["job_id"], request)


@app.get("/jobs", response_model=ActiveJobsResponse, dependencies=[Depends(require_api_key)])
async def list_jobs(request: Request) -> ActiveJobsResponse:
    jobs = [_status_response(status, request) for status in build_queue.list_active() if status]
    return ActiveJobsResponse(jobs=jobs)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(require_api_key)])
async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    status = build_queue.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return _status_response(status, request)


@app.get("/jobs/{job_id}/download", dependencies=[Depends(require_api_key)])
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


@app.get("/jobs/{job_id}/log", dependencies=[Depends(require_api_key)])
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


async def _payload_from_form(
    request: Request,
    model_class: type[AndroidBuildRequest] | type[WindowsBuildRequest],
) -> tuple[dict[str, Any], Path | None]:
    form = await _read_form(request)
    assets_dir: Path | None = None

    try:
        payload = _source_payload_from_form(form)
        icon, assets_dir = await _store_icon_assets(form)
        if icon:
            payload["icon"] = icon

        if model_class is WindowsBuildRequest:
            payload["package_format"] = _optional_text(form, "package_format") or "msi"

        return _validated_payload(model_class, payload), assets_dir
    except Exception:
        _cleanup_asset_dir(assets_dir)
        raise


async def _read_form(request: Request) -> Any:
    try:
        return await request.form()
    except (AssertionError, RuntimeError) as exc:
        if "python-multipart" in str(exc):
            raise HTTPException(
                status_code=500,
                detail="python-multipart is required for form uploads. Install requirements.txt.",
            ) from exc
        raise


def _source_payload_from_form(form: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "html": _required_text(form, "html"),
        "css": _text(form, "css", ""),
        "js": _text(form, "js", ""),
        "app_name": _text(form, "app_name", "api2app generated"),
        "bundle": _text(form, "bundle", "com.api2app.generated"),
        "version": _text(form, "version", "0.0.1"),
        "description": _text(form, "description", "Generated WebView application"),
    }

    header = _header_from_form(form)
    if header is not None:
        payload["header"] = header

    menu = _menu_from_form(form)
    if menu is not None:
        payload["menu"] = menu

    return payload


def _header_from_form(form: Any) -> dict[str, Any] | None:
    header = _json_object_field(form, "header")
    explicit_fields = {
        "header_enabled",
        "header_title",
        "header_subtitle",
        "header_background_color",
        "header_text_color",
    }
    if header is None and not explicit_fields.intersection(form.keys()):
        return None

    data = dict(header or {})
    enabled = _optional_bool(form, "header_enabled")
    if enabled is not None:
        data["enabled"] = enabled
    _set_optional(data, "title", _optional_text(form, "header_title"))
    _set_optional(data, "subtitle", _optional_text(form, "header_subtitle"))
    _set_optional(data, "background_color", _optional_text(form, "header_background_color"))
    _set_optional(data, "text_color", _optional_text(form, "header_text_color"))
    return data


def _menu_from_form(form: Any) -> dict[str, Any] | None:
    menu = _json_object_field(form, "menu")
    explicit_fields = {
        "menu_enabled",
        "menu_position",
        "menu_background_color",
        "menu_text_color",
        "menu_items",
        "menu_items_json",
        "menu_label",
        "menu_href",
        "menu_onclick",
    }
    if menu is None and not explicit_fields.intersection(form.keys()):
        return None

    data = dict(menu or {})
    enabled = _optional_bool(form, "menu_enabled")
    if enabled is not None:
        data["enabled"] = enabled
    _set_optional(data, "position", _optional_text(form, "menu_position"))
    _set_optional(data, "background_color", _optional_text(form, "menu_background_color"))
    _set_optional(data, "text_color", _optional_text(form, "menu_text_color"))

    items = _menu_items_from_form(form)
    if items is not None:
        data["items"] = items
    return data


def _menu_items_from_form(form: Any) -> list[dict[str, Any]] | None:
    raw_items = _optional_text(form, "menu_items")
    if raw_items is None:
        raw_items = _optional_text(form, "menu_items_json")
    if raw_items is not None:
        try:
            parsed = json.loads(raw_items)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="menu_items must be a valid JSON array") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail="menu_items must be a JSON array")
        return parsed

    labels = _text_list(form, "menu_label")
    if not labels:
        return None

    hrefs = _text_list(form, "menu_href")
    onclicks = _text_list(form, "menu_onclick")
    items = []
    for index, label in enumerate(labels):
        item: dict[str, Any] = {
            "label": label,
            "href": hrefs[index] if index < len(hrefs) and hrefs[index] else "#",
        }
        if index < len(onclicks) and onclicks[index]:
            item["onclick"] = onclicks[index]
        items.append(item)
    return items


async def _store_icon_assets(form: Any) -> tuple[dict[str, Any] | None, Path | None]:
    icon_file = _file_field(form, "icon_file", "icon", "image_file", "image", "png_file")
    icon_url = _first_optional_text(form, "icon_url", "image_url", "png_url")
    ico_file = _file_field(form, "ico_file", "windows_icon_file")
    ico_url = _first_optional_text(form, "ico_url", "windows_icon_url")

    if icon_file and icon_url:
        raise HTTPException(status_code=422, detail="Use either icon_file or icon_url, not both")
    if ico_file and ico_url:
        raise HTTPException(status_code=422, detail="Use either ico_file or ico_url, not both")
    if not any((icon_file, icon_url, ico_file, ico_url)):
        return None, None

    assets_dir = settings.uploads_dir / uuid.uuid4().hex
    assets_dir.mkdir(parents=True, exist_ok=True)
    icon: dict[str, Any] = {"asset_dir": str(assets_dir)}

    try:
        if icon_file:
            icon["source_path"] = str(await _save_upload_image(icon_file, assets_dir, "source", "icon_file"))
        elif icon_url:
            icon["source_path"] = str(_download_image(icon_url, assets_dir, "source", "icon_url"))

        if ico_file:
            icon["ico_path"] = str(await _save_upload_image(ico_file, assets_dir, "windows", "ico_file"))
        elif ico_url:
            icon["ico_path"] = str(_download_image(ico_url, assets_dir, "windows", "ico_url"))
    except Exception:
        _cleanup_asset_dir(assets_dir)
        raise

    return icon, assets_dir


async def _save_upload_image(upload: UploadFile, assets_dir: Path, stem: str, field_name: str) -> Path:
    suffix = _suffix_for_upload(upload)
    target = assets_dir / f"{stem}{suffix}"
    total = 0

    try:
        upload.file.seek(0)
        with target.open("wb") as output:
            while True:
                chunk = upload.file.read(IMAGE_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_image_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{field_name} is too large: limit is {settings.max_image_bytes} bytes",
                    )
                output.write(chunk)
    finally:
        upload.file.close()

    if total == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"{field_name} is empty")

    _validate_image_file(target, field_name)
    return target


def _download_image(url: str, assets_dir: Path, stem: str, field_name: str) -> Path:
    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail=f"{field_name} must be an http or https URL")

    response: requests.Response | None = None
    try:
        response = requests.get(cleaned_url, stream=True, timeout=(5, 30))
        response.raise_for_status()
    except requests.RequestException as exc:
        if response is not None:
            response.close()
        raise HTTPException(status_code=400, detail=f"Could not download {field_name}: {exc}") from exc

    try:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail=f"{field_name} URL must return an image")

        suffix = _safe_image_suffix(Path(parsed.path).suffix)
        if suffix == ".img":
            suffix = _safe_image_suffix(mimetypes.guess_extension(content_type or ""))
        target = assets_dir / f"{stem}{suffix}"
        total = 0
        with target.open("wb") as output:
            for chunk in response.iter_content(chunk_size=IMAGE_CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > settings.max_image_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{field_name} is too large: limit is {settings.max_image_bytes} bytes",
                    )
                output.write(chunk)

        if total == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=f"{field_name} URL returned an empty file")

        _validate_image_file(target, field_name)
        return target
    finally:
        response.close()


def _validate_image_file(path: Path, field_name: str) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="Pillow is required to validate image uploads. Install requirements.txt.",
        ) from exc

    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid image file") from exc

    if width < 1 or height < 1:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"{field_name} must have non-zero dimensions")


def _validated_payload(
    model_class: type[AndroidBuildRequest] | type[WindowsBuildRequest],
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return model_to_dict(model_class(**payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=jsonable_encoder(exc.errors())) from exc


def _json_object_field(form: Any, name: str) -> dict[str, Any] | None:
    raw = _optional_text(form, name)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=f"{name} must be a JSON object")
    return parsed


def _text(form: Any, name: str, default: str) -> str:
    value = form.get(name)
    if value is None:
        return default
    if _is_upload(value):
        raise HTTPException(status_code=422, detail=f"{name} must be a form field, not a file")
    return str(value)


def _required_text(form: Any, name: str) -> str:
    value = _optional_text(form, name)
    if value is None:
        raise HTTPException(status_code=422, detail=f"Missing required form field: {name}")
    return value


def _optional_text(form: Any, name: str) -> str | None:
    value = form.get(name)
    if value is None:
        return None
    if _is_upload(value):
        raise HTTPException(status_code=422, detail=f"{name} must be a form field, not a file")
    text = str(value)
    return text if text != "" else None


def _first_optional_text(form: Any, *names: str) -> str | None:
    for name in names:
        value = _optional_text(form, name)
        if value is not None:
            return value
    return None


def _optional_bool(form: Any, name: str) -> bool | None:
    value = _optional_text(form, name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in TRUE_FORM_VALUES:
        return True
    if normalized in FALSE_FORM_VALUES:
        return False
    raise HTTPException(status_code=422, detail=f"{name} must be a boolean value")


def _text_list(form: Any, name: str) -> list[str]:
    values = []
    for value in form.getlist(name):
        if _is_upload(value):
            raise HTTPException(status_code=422, detail=f"{name} must be a form field, not a file")
        text = str(value)
        if text:
            values.append(text)
    return values


def _file_field(form: Any, *names: str) -> UploadFile | None:
    for name in names:
        value = form.get(name)
        if value is None:
            continue
        if not _is_upload(value):
            raise HTTPException(status_code=422, detail=f"{name} must be a file field")
        if value.filename:
            return value
    return None


def _is_upload(value: Any) -> bool:
    return isinstance(value, UploadFile)


def _suffix_for_upload(upload: UploadFile) -> str:
    suffix = _safe_image_suffix(Path(upload.filename or "").suffix)
    if suffix != ".img":
        return suffix
    return _safe_image_suffix(mimetypes.guess_extension(upload.content_type or ""))


def _safe_image_suffix(suffix: str | None) -> str:
    if not suffix:
        return ".img"
    normalized = suffix.lower()
    return normalized if normalized in ALLOWED_IMAGE_SUFFIXES else ".img"


def _set_optional(data: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        data[key] = value


def _cleanup_asset_dir(path: Path | None) -> None:
    if path:
        shutil.rmtree(path, ignore_errors=True)


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
