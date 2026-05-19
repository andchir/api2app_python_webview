from __future__ import annotations

import asyncio
import base64
import binascii
import html as html_lib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings


APP_TEMPLATE = '''from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import COLUMN


class GeneratedWebApp(toga.App):
    def startup(self):
        self.main_window = toga.MainWindow(title=self.formal_name, size=(1024, 768))

        webview = toga.WebView(style=Pack(flex=1))
        index_path = Path(__file__).parent / "resources" / "generated" / "index.html"
        webview.set_content("https://api2app.local/", index_path.read_text(encoding="utf-8"))

        box = toga.Box(children=[webview], style=Pack(direction=COLUMN, flex=1))
        self.main_window.content = box
        self.main_window.show()


def main():
    return GeneratedWebApp()
'''


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def run_build(job: dict[str, Any], settings: Settings) -> dict[str, Any]:
    job_id = job["job_id"]
    target = job["target"]
    package_format = job.get("package_format")
    workspace = settings.workspaces_dir / job_id
    artifact_dir = settings.artifacts_dir / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "build.log"

    if workspace.exists():
        shutil.rmtree(workspace)

    try:
        _copy_project(settings.base_briefcase_project, workspace)
        _write_generated_app(workspace, job)

        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"job_id={job_id}\ntarget={target}\nstarted_at={utc_now()}\n\n")
            for command in _build_commands(settings, target, package_format):
                await _run_command(command, workspace, log, settings.build_timeout_seconds)

        artifact = _find_artifact(workspace, target, package_format)
        copied_artifact = artifact_dir / artifact.name
        shutil.copy2(artifact, copied_artifact)

        return {
            "job_id": job_id,
            "target": target,
            "status": "completed",
            "created_at": job["created_at"],
            "updated_at": utc_now(),
            "started_at": job.get("started_at"),
            "finished_at": utc_now(),
            "artifact_name": copied_artifact.name,
            "artifact_path": str(copied_artifact),
            "log_path": str(log_path),
            "message": "Build completed.",
        }
    except Exception as exc:
        _append_failure(log_path, exc)
        return {
            "job_id": job_id,
            "target": target,
            "status": "failed",
            "created_at": job["created_at"],
            "updated_at": utc_now(),
            "started_at": job.get("started_at"),
            "finished_at": utc_now(),
            "log_path": str(log_path),
            "message": str(exc),
        }
    finally:
        if not settings.keep_workspaces and workspace.exists():
            shutil.rmtree(workspace)


def write_result(result: dict[str, Any], settings: Settings) -> None:
    result_dir = settings.artifacts_dir / result["job_id"]
    result_dir.mkdir(parents=True, exist_ok=True)
    result.setdefault(
        "expires_at",
        (datetime.now(UTC) + timedelta(seconds=settings.artifact_ttl_seconds)).isoformat(),
    )
    result_path = result_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def load_result(job_id: str, settings: Settings) -> dict[str, Any] | None:
    result_path = settings.artifacts_dir / job_id / "result.json"
    if not result_path.exists():
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))


def delete_result(job_id: str, settings: Settings) -> None:
    shutil.rmtree(settings.artifacts_dir / job_id, ignore_errors=True)


def is_result_expired(result: dict[str, Any]) -> bool:
    expires_at = _parse_datetime(result.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(UTC)


def cleanup_workspaces(settings: Settings) -> None:
    settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
    for child in settings.workspaces_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def cleanup_expired_results(settings: Settings) -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    for child in settings.artifacts_dir.iterdir():
        if not child.is_dir():
            continue

        result_path = child / "result.json"
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                expires_at = _parse_datetime(result.get("expires_at"))
            except (OSError, json.JSONDecodeError):
                expires_at = None
        else:
            expires_at = None

        if expires_at is None:
            modified_at = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC)
            expires_at = modified_at + timedelta(seconds=settings.artifact_ttl_seconds)

        if expires_at <= now:
            shutil.rmtree(child, ignore_errors=True)


def strip_markdown_code_fence(source: str) -> str:
    text = source.strip()
    if not text:
        return text

    lines = text.splitlines()
    opening = re.match(r"^\s*(`{3,}|~{3,}).*$", lines[0])
    if not opening:
        return text

    marker = opening.group(1)
    closing = re.match(rf"^\s*{re.escape(marker)}\s*$", lines[-1])
    if closing:
        lines = lines[1:-1]
    else:
        lines = lines[1:]

    return "\n".join(lines).strip()


def validate_html_document(source: str) -> str:
    document = strip_markdown_code_fence(source)
    lowered = document.lower()
    errors: list[str] = []

    if not re.match(r"^<!doctype\s+html\s*>", document, flags=re.IGNORECASE):
        errors.append("must start with <!doctype html>")
    if not re.match(r"^<!doctype\s+html\s*>\s*<html\b[^>]*>", document, flags=re.IGNORECASE):
        errors.append("must have an opening <html> tag immediately after <!doctype html>")
    if not re.search(r"</html>\s*$", document, flags=re.IGNORECASE):
        errors.append("must end with </html>")

    head_open = _tag_start(lowered, "head")
    head_close = _tag_close(lowered, "head")
    body_open = _tag_start(lowered, "body")
    body_close = _tag_close(lowered, "body")
    html_close = lowered.rfind("</html>")

    if head_open == -1:
        errors.append("must include an opening <head> tag")
    if head_close == -1:
        errors.append("must include a closing </head> tag")
    if body_open == -1:
        errors.append("must include an opening <body> tag")
    if body_close == -1:
        errors.append("must include a closing </body> tag")

    if head_open != -1 and head_close != -1 and head_open > head_close:
        errors.append("<head> must be closed after it is opened")
    if body_open != -1 and body_close != -1 and body_open > body_close:
        errors.append("<body> must be closed after it is opened")
    if head_close != -1 and body_open != -1 and head_close > body_open:
        errors.append("<head> must be closed before <body> starts")
    if body_close != -1 and html_close != -1 and body_close > html_close:
        errors.append("</body> must appear before </html>")

    if errors:
        raise ValueError("Invalid HTML document: " + "; ".join(errors))

    return document


def compose_html(request: dict[str, Any]) -> str:
    html = validate_html_document(request["html"])
    css = strip_markdown_code_fence(request.get("css", ""))
    js = strip_markdown_code_fence(request.get("js", ""))
    document = html.strip()
    if "<html" not in document.lower():
        document = f'<!doctype html>\n<html>\n<head><meta charset="utf-8"></head>\n<body>\n{document}\n</body>\n</html>'

    shell = _build_app_shell(request)
    bottom_shell = _build_bottom_menu(request)
    generated_css = _build_app_shell_css(request)
    if generated_css:
        document = _insert_before(document, "</head>", f"\n<style>\n{generated_css}\n</style>\n", fallback_before="</body>")

    if shell:
        document = _insert_after_body_open(document, shell)
    if bottom_shell:
        document = _insert_before(document, "</body>", bottom_shell)

    if css:
        css_tag = f"\n<style>\n{css}\n</style>\n"
        document = _insert_before(document, "</head>", css_tag, fallback_before="</body>")

    if js:
        script_tag = f"\n<script>\n{js}\n</script>\n"
        document = _insert_before(document, "</body>", script_tag)

    return document


def artifact_path(job_id: str, settings: Settings) -> Path | None:
    result = load_result(job_id, settings)
    if not result or result.get("status") != "completed":
        return None

    path_value = result.get("artifact_path")
    if not path_value:
        return None

    path = Path(path_value)
    if path.exists() and path.is_file():
        return path
    return None


def log_path(job_id: str, settings: Settings) -> Path | None:
    result = load_result(job_id, settings)
    if result and result.get("log_path"):
        path = Path(result["log_path"])
    else:
        path = settings.artifacts_dir / job_id / "build.log"

    if path.exists() and path.is_file():
        return path
    return None


def _copy_project(source: Path, workspace: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Briefcase project not found: {source}")

    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored = {"build", "logs", "__pycache__", ".pytest_cache"}
        ignored.update(name for name in names if name.endswith((".pyc", ".pyo")))
        return ignored

    shutil.copytree(source, workspace, ignore=ignore)


def _write_generated_app(workspace: Path, job: dict[str, Any]) -> None:
    request = job["request"]
    package_dir = workspace / "src" / "api2app"
    generated_dir = package_dir / "resources" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "index.html").write_text(
        compose_html(request),
        encoding="utf-8",
    )
    (package_dir / "app.py").write_text(APP_TEMPLATE, encoding="utf-8")
    _write_icons(workspace, request)
    _patch_pyproject(workspace / "pyproject.toml", request)


def _patch_pyproject(pyproject_path: Path, request: dict[str, Any]) -> None:
    text = pyproject_path.read_text(encoding="utf-8")
    replacements = {
        "project_name": request.get("app_name", "api2app generated"),
        "version": request.get("version", "0.0.1"),
        "bundle": request.get("bundle", "com.api2app.generated"),
        "formal_name": request.get("app_name", "api2app generated"),
        "description": request.get("description", "Generated WebView application"),
    }

    for key, value in replacements.items():
        text = re.sub(
            rf'^({re.escape(key)}\s*=\s*)".*"$',
            lambda match, replacement=value: f'{match.group(1)}"{_escape_toml_string(replacement)}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )

    pyproject_path.write_text(text, encoding="utf-8")


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_app_shell(request: dict[str, Any]) -> str:
    header = request.get("header")
    menu = request.get("menu")
    parts: list[str] = []

    if header and header.get("enabled", True):
        title = html_lib.escape(header.get("title") or request.get("app_name") or "")
        subtitle = html_lib.escape(header.get("subtitle") or "")
        subtitle_html = f'<p class="api2app-header-subtitle">{subtitle}</p>' if subtitle else ""
        parts.append(
            '<header class="api2app-header">'
            f'<h1 class="api2app-header-title">{title}</h1>'
            f"{subtitle_html}"
            "</header>"
        )

    if menu and menu.get("enabled", True) and menu.get("items"):
        items = "".join(_render_menu_item(item) for item in menu["items"])
        menu_html = f'<nav class="api2app-menu" aria-label="Application menu">{items}</nav>'
        if menu.get("position", "top") == "top":
            parts.append(menu_html)

    return "".join(parts)


def _build_bottom_menu(request: dict[str, Any]) -> str:
    menu = request.get("menu")
    if not menu or not menu.get("enabled", True) or not menu.get("items") or menu.get("position") != "bottom":
        return ""
    items = "".join(_render_menu_item(item) for item in menu["items"])
    return f'<nav class="api2app-menu api2app-menu-bottom" aria-label="Application menu">{items}</nav>'


def _build_app_shell_css(request: dict[str, Any]) -> str:
    header = request.get("header") or {}
    menu = request.get("menu") or {}
    if not header and not menu:
        return ""

    header_background = header.get("background_color", "#111827")
    header_text = header.get("text_color", "#ffffff")
    menu_background = menu.get("background_color", "#f8fafc")
    menu_text = menu.get("text_color", "#111827")
    menu_position = menu.get("position", "top")
    bottom_menu = menu and menu.get("enabled", True) and menu.get("items") and menu_position == "bottom"
    bottom_padding = "72px" if bottom_menu else "0"

    return f"""
html, body {{
    min-height: 100%;
}}

body {{
    margin: 0;
    padding-bottom: {bottom_padding};
}}

.api2app-header {{
    background: {header_background};
    color: {header_text};
    padding: 18px 20px;
}}

.api2app-header-title {{
    font-size: 22px;
    line-height: 1.2;
    margin: 0;
}}

.api2app-header-subtitle {{
    font-size: 14px;
    line-height: 1.4;
    margin: 6px 0 0;
    opacity: 0.85;
}}

.api2app-menu {{
    align-items: center;
    background: {menu_background};
    border-bottom: 1px solid rgba(15, 23, 42, 0.12);
    color: {menu_text};
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding: 8px 12px;
}}

.api2app-menu a {{
    color: inherit;
    display: inline-flex;
    font-size: 14px;
    line-height: 1;
    padding: 10px 12px;
    text-decoration: none;
    white-space: nowrap;
}}

.api2app-menu-bottom {{
    border-bottom: 0;
    border-top: 1px solid rgba(15, 23, 42, 0.12);
    bottom: 0;
    box-sizing: border-box;
    left: 0;
    position: fixed;
    right: 0;
    z-index: 1000;
}}
""".strip()


def _render_menu_item(item: dict[str, Any]) -> str:
    label = html_lib.escape(str(item.get("label", "")))
    href = html_lib.escape(str(item.get("href") or "#"), quote=True)
    onclick = item.get("onclick")
    onclick_attr = f' onclick="{html_lib.escape(str(onclick), quote=True)}"' if onclick else ""
    return f'<a href="{href}"{onclick_attr}>{label}</a>'


def _write_icons(workspace: Path, request: dict[str, Any]) -> None:
    icon = request.get("icon") or {}
    png_base64 = icon.get("png_base64")
    ico_base64 = icon.get("ico_base64")
    if not png_base64 and not ico_base64:
        return

    resources_dir = workspace / "src" / "api2app" / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    if png_base64:
        png_bytes = _decode_base64_asset(png_base64)
        source_png = resources_dir / "icon-source.png"
        source_png.write_bytes(png_bytes)
        _generate_png_icons(source_png, resources_dir)

        if not ico_base64:
            _generate_ico(source_png, resources_dir / "icon.ico")

    if ico_base64:
        (resources_dir / "icon.ico").write_bytes(_decode_base64_asset(ico_base64))


def _decode_base64_asset(value: str) -> bytes:
    if "," in value and value.strip().lower().startswith("data:"):
        value = value.split(",", 1)[1]
    value = "".join(value.split())
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Icon must be a valid base64 value") from exc


def _generate_png_icons(source_png: Path, resources_dir: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate app icons. Install requirements.txt.") from exc

    sizes = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }

    with Image.open(source_png) as image:
        image = image.convert("RGBA")
        for folder, size in sizes.items():
            target_dir = resources_dir / "android" / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            resized = image.resize((size, size), Image.LANCZOS)
            for filename in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
                resized.save(target_dir / filename, format="PNG")

        playstore = image.resize((512, 512), Image.LANCZOS)
        (resources_dir / "android").mkdir(parents=True, exist_ok=True)
        playstore.save(resources_dir / "android" / "playstore-icon.png", format="PNG")


def _generate_ico(source_png: Path, target_ico: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate Windows ICO. Install requirements.txt.") from exc

    with Image.open(source_png) as image:
        image.convert("RGBA").save(target_ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


def _build_commands(settings: Settings, target: str, package_format: str | None) -> list[list[str]]:
    briefcase = list(settings.briefcase_command)
    commands = [
        [*briefcase, "create", target],
        [*briefcase, "build", target],
    ]

    if target == "android":
        commands.append([*briefcase, "package", target])
    elif target == "windows" and package_format != "exe":
        package_args = [*briefcase, "package", target]
        if package_format:
            package_args.extend(["-p", package_format])
        commands.append(package_args)

    return commands


async def _run_command(command: list[str], cwd: Path, log, timeout_seconds: int) -> None:
    log.write(f"$ {' '.join(command)}\n")
    log.flush()
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
        )
        return_code = await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        raise RuntimeError(f"Command timed out after {timeout_seconds} seconds: {' '.join(command)}") from exc

    log.write(f"exit_code={return_code}\n\n")
    log.flush()
    if return_code != 0:
        raise RuntimeError(f"Build command failed with exit code {return_code}: {' '.join(command)}")


def _find_artifact(workspace: Path, target: str, package_format: str | None) -> Path:
    if target == "android":
        suffixes = [".apk", ".aab"]
    elif package_format == "exe":
        suffixes = [".exe"]
    elif package_format:
        suffixes = [f".{package_format}"]
    else:
        suffixes = [".msi", ".exe", ".zip"]

    candidates = [
        path
        for path in workspace.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes and "node_modules" not in path.parts
    ]
    if not candidates:
        raise FileNotFoundError(f"No {target} artifact found with suffixes: {', '.join(suffixes)}")

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _insert_before(document: str, marker: str, content: str, fallback_before: str | None = None) -> str:
    lower = document.lower()
    index = lower.rfind(marker.lower())
    if index == -1 and fallback_before:
        index = lower.rfind(fallback_before.lower())
    if index == -1:
        return f"{document}\n{content}"
    return f"{document[:index]}{content}{document[index:]}"


def _insert_after_body_open(document: str, content: str) -> str:
    match = re.search(r"<body\b[^>]*>", document, flags=re.IGNORECASE)
    if not match:
        return f"{content}\n{document}"
    return f"{document[:match.end()]}\n{content}\n{document[match.end():]}"


def _tag_start(document: str, tag: str) -> int:
    match = re.search(rf"<{tag}\b[^>]*>", document, flags=re.IGNORECASE)
    return match.start() if match else -1


def _tag_close(document: str, tag: str) -> int:
    return document.lower().find(f"</{tag}>")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _append_failure(log_path: Path, exc: Exception) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\nFAILED: {exc}\n")
