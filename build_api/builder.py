from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings


APP_TEMPLATE = '''from importlib import resources
import json

import toga
from toga.style import Pack
from toga.style.pack import COLUMN


def _load_generated_html():
    return (
        resources.files(__package__)
        .joinpath("resources", "generated", "index.html")
        .read_text(encoding="utf-8")
    )


def _load_generated_config():
    try:
        return json.loads(
            resources.files(__package__)
            .joinpath("resources", "generated", "app_config.json")
            .read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def _set_webview_content(webview, html):
    native = getattr(getattr(webview, "_impl", None), "native", None)
    load_with_base_url = getattr(native, "loadDataWithBaseURL", None)
    if load_with_base_url:
        load_with_base_url("https://api2app.local/", html, "text/html", "UTF-8", None)
    else:
        webview.set_content("https://api2app.local/", html)


def _command_id(index):
    return f"api2app-menu-{index}"


def _menu_group_label(menu):
    label = str(menu.get("label") or menu.get("title") or "Menu").strip()
    return label or "Menu"


class GeneratedWebApp(toga.App):
    def startup(self):
        config = _load_generated_config()
        title = self._native_title(config)
        self.main_window = toga.MainWindow(title=title, size=(1024, 768))

        try:
            html = _load_generated_html()
        except Exception as exc:
            self.main_window.content = toga.Box(
                children=[
                    toga.Label(
                        f"Could not load generated HTML: {exc}",
                        style=Pack(padding=16),
                    )
                ],
                style=Pack(direction=COLUMN, flex=1),
            )
            self.main_window.show()
            return

        webview = toga.WebView(style=Pack(flex=1))
        self.webview = webview
        _set_webview_content(webview, html)
        self._install_native_menu(config.get("menu") or {})
        box = toga.Box(children=[webview], style=Pack(direction=COLUMN, flex=1))
        self.main_window.content = box
        self.main_window.show()

    def _native_title(self, config):
        header = config.get("header") or {}
        if header.get("enabled", True) and header.get("title"):
            return header["title"]
        return config.get("app_name") or self.formal_name

    def _install_native_menu(self, menu):
        if not menu.get("enabled", True):
            return

        menu_group = toga.Group(
            _menu_group_label(menu),
            order=0,
            id="api2app-menu",
        )
        for index, item in enumerate(menu.get("items") or []):
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            self.commands.add(
                toga.Command(
                    self._menu_action(item),
                    text=label,
                    group=menu_group,
                    order=index,
                    id=_command_id(index),
                )
            )

    def _menu_action(self, item):
        def action(command):
            onclick = item.get("onclick")
            href = item.get("href") or "#"
            if onclick:
                self.webview.evaluate_javascript(str(onclick))
            elif str(href).startswith(("http://", "https://")):
                self.webview.url = str(href)
            else:
                self.webview.evaluate_javascript(
                    "window.location.href = " + json.dumps(str(href)) + ";"
                )

        return action


def main():
    return GeneratedWebApp()
'''

BRIEFCASE_ICON = "resources/generated/icon"
ANDROID_ICON_SIZES = {
    "mipmap-mdpi": {"launcher": 48, "adaptive": 108, "splash": 320},
    "mipmap-hdpi": {"launcher": 72, "adaptive": 162, "splash": 480},
    "mipmap-xhdpi": {"launcher": 96, "adaptive": 216, "splash": 640},
    "mipmap-xxhdpi": {"launcher": 144, "adaptive": 324, "splash": 960},
    "mipmap-xxxhdpi": {"launcher": 192, "adaptive": 432, "splash": 1280},
}


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
                if _is_create_command(command, target):
                    _install_created_app_resources(workspace, job["request"], target, log)

        artifact = _find_artifact(workspace, target, package_format)
        copied_artifact = artifact_dir / artifact.name
        shutil.copy2(artifact, copied_artifact)
        stored_log_path = _stored_log_path(log_path, workspace, artifact_dir)

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
            "log_path": str(stored_log_path),
            "message": "Build completed.",
        }
    except Exception as exc:
        _append_failure(log_path, exc)
        stored_log_path = _stored_log_path(log_path, workspace, artifact_dir)
        return {
            "job_id": job_id,
            "target": target,
            "status": "failed",
            "created_at": job["created_at"],
            "updated_at": utc_now(),
            "started_at": job.get("started_at"),
            "finished_at": utc_now(),
            "log_path": str(stored_log_path),
            "message": str(exc),
        }
    finally:
        _cleanup_request_assets(job, settings)
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

    text = re.sub(r'^```html\n?', '', text)
    text = re.sub(r'\n?```$', '', text)

    return text


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


def _stored_log_path(wrapper_log_path: Path, workspace: Path, artifact_dir: Path) -> Path:
    briefcase_log_path = _briefcase_saved_log_path(wrapper_log_path, workspace)
    if not briefcase_log_path:
        return wrapper_log_path

    stored_path = artifact_dir / briefcase_log_path.name
    if stored_path == wrapper_log_path:
        return wrapper_log_path

    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(briefcase_log_path, stored_path)
    except OSError:
        return wrapper_log_path
    return stored_path


def _briefcase_saved_log_path(wrapper_log_path: Path, workspace: Path) -> Path | None:
    try:
        wrapper_log = wrapper_log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    matches = re.findall(r"^Log saved to (?P<path>.+?)\s*$", wrapper_log, flags=re.MULTILINE)
    workspace_root = workspace.resolve()
    for value in reversed(matches):
        path = Path(value.strip())
        if not path.is_absolute():
            path = workspace / path
        resolved_path = path.resolve()
        if not _is_relative_to(resolved_path, workspace_root):
            continue
        if resolved_path.exists() and resolved_path.is_file():
            return resolved_path
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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
    (generated_dir / "app_config.json").write_text(
        json.dumps(_native_app_config(request), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (package_dir / "app.py").write_text(APP_TEMPLATE, encoding="utf-8")
    _write_icons(workspace, request)
    _patch_pyproject(workspace / "pyproject.toml", request)


def _native_app_config(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_name": request.get("app_name", "api2app generated"),
        "header": request.get("header") or {},
        "menu": request.get("menu") or {},
    }


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

    if _has_custom_icon(request):
        text = _set_toml_section_value(
            text,
            "tool.briefcase.app.api2app",
            "icon",
            BRIEFCASE_ICON,
        )

    pyproject_path.write_text(text, encoding="utf-8")


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _set_toml_section_value(text: str, section: str, key: str, value: str) -> str:
    section_match = re.search(
        rf'(?ms)^(\[{re.escape(section)}\]\s*\n)(.*?)(?=^\[|\Z)',
        text,
    )
    if not section_match:
        return text

    header, body = section_match.groups()
    line = f'{key} = "{_escape_toml_string(value)}"'
    key_pattern = rf'(?m)^({re.escape(key)}\s*=\s*).*$'
    if re.search(key_pattern, body):
        body = re.sub(key_pattern, line, body, count=1)
    else:
        if body and not body.endswith("\n"):
            body += "\n"
        body += f"{line}\n"

    return text[: section_match.start()] + header + body + text[section_match.end():]


def _has_custom_icon(request: dict[str, Any]) -> bool:
    icon = request.get("icon") or {}
    return bool(icon.get("source_path") or icon.get("ico_path"))


def _write_icons(workspace: Path, request: dict[str, Any]) -> None:
    icon = request.get("icon") or {}
    source_path = _icon_path(icon.get("source_path"), "Icon image")
    ico_path = _icon_path(icon.get("ico_path"), "Windows icon image")
    if not source_path and not ico_path:
        return

    resources_dir = workspace / "src" / "api2app" / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    briefcase_icon = workspace / BRIEFCASE_ICON

    if source_path:
        _generate_png_icons(source_path, resources_dir)
        _generate_briefcase_png_icons(source_path, briefcase_icon)

    if ico_path:
        _generate_ico(ico_path, resources_dir / "icon.ico")
        _generate_ico(ico_path, briefcase_icon.with_suffix(".ico"))
    elif source_path:
        _generate_ico(source_path, resources_dir / "icon.ico")
        _generate_ico(source_path, briefcase_icon.with_suffix(".ico"))


def _icon_path(value: str | None, label: str) -> Path | None:
    if not value:
        return None

    path = Path(value)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _generate_png_icons(source_image: Path, resources_dir: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate app icons. Install requirements.txt.") from exc

    with Image.open(source_image) as image:
        for folder, sizes in ANDROID_ICON_SIZES.items():
            target_dir = resources_dir / "android" / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            launcher = _resize_to_square(image, sizes["launcher"])
            launcher.save(target_dir / "ic_launcher.png", format="PNG")
            launcher.save(target_dir / "ic_launcher_round.png", format="PNG")
            foreground = _resize_to_square(
                image,
                sizes["adaptive"],
                content_size=round(sizes["adaptive"] * 0.66),
            )
            foreground.save(target_dir / "ic_launcher_foreground.png", format="PNG")
            splash = _resize_to_square(
                image,
                sizes["splash"],
                content_size=round(sizes["splash"] * 0.6),
            )
            splash.save(target_dir / "splash.png", format="PNG")

        playstore = _resize_to_square(image, 512)
        (resources_dir / "android").mkdir(parents=True, exist_ok=True)
        playstore.save(resources_dir / "android" / "playstore-icon.png", format="PNG")


def _generate_briefcase_png_icons(source_image: Path, icon_base: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate app icons. Install requirements.txt.") from exc

    icon_base.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source_image) as image:
        for sizes in ANDROID_ICON_SIZES.values():
            launcher = _resize_to_square(image, sizes["launcher"])
            launcher.save(_briefcase_icon_path(icon_base, "square", sizes["launcher"]), format="PNG")
            launcher.save(_briefcase_icon_path(icon_base, "round", sizes["launcher"]), format="PNG")

            foreground = _resize_to_square(
                image,
                sizes["adaptive"],
                content_size=round(sizes["adaptive"] * 0.66),
            )
            foreground.save(_briefcase_icon_path(icon_base, "adaptive", sizes["adaptive"]), format="PNG")

            splash = _resize_to_square(
                image,
                sizes["splash"],
                content_size=round(sizes["splash"] * 0.6),
            )
            splash.save(_briefcase_icon_path(icon_base, "square", sizes["splash"]), format="PNG")


def _briefcase_icon_path(icon_base: Path, variant: str, size: int) -> Path:
    return icon_base.with_name(f"{icon_base.name}-{variant}-{size}.png")


def _generate_ico(source_image: Path, target_ico: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate Windows ICO. Install requirements.txt.") from exc

    target_ico.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_image) as image:
        _resize_to_square(image, 256).save(
            target_ico,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
        )


def _resize_to_square(image: Any, size: int, content_size: int | None = None) -> Any:
    from PIL import Image

    content_size = content_size or size
    resized = image.convert("RGBA")
    resized.thumbnail((content_size, content_size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    left = (size - resized.width) // 2
    top = (size - resized.height) // 2
    canvas.alpha_composite(resized, (left, top))
    return canvas


def _is_create_command(command: list[str], target: str) -> bool:
    return len(command) >= 2 and command[-2:] == ["create", target]


def _install_created_app_resources(workspace: Path, request: dict[str, Any], target: str, log) -> None:
    if target != "android" or not (request.get("icon") or {}).get("source_path"):
        return

    source_dir = workspace / "src" / "api2app" / "resources" / "android"
    target_dir = workspace / "build" / "api2app" / "android" / "gradle" / "app" / "src" / "main" / "res"
    if not source_dir.exists() or not target_dir.exists():
        return

    copied = 0
    for source_path in source_dir.glob("mipmap-*/*.png"):
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied += 1

    if copied:
        log.write(f"Installed {copied} generated Android icon resources into Gradle res.\n\n")
        log.flush()


def _cleanup_request_assets(job: dict[str, Any], settings: Settings) -> None:
    icon = job.get("request", {}).get("icon") or {}
    asset_dir_value = icon.get("asset_dir")
    if not asset_dir_value:
        return

    try:
        asset_dir = Path(asset_dir_value).resolve()
        uploads_dir = settings.uploads_dir.resolve()
        asset_dir.relative_to(uploads_dir)
    except (OSError, ValueError):
        return

    shutil.rmtree(asset_dir, ignore_errors=True)


def _build_commands(settings: Settings, target: str, package_format: str | None) -> list[list[str]]:
    briefcase = list(settings.briefcase_command)
    commands = [
        [*briefcase, "create", target],
        [*briefcase, "build", target],
    ]

    if target == "android":
        commands.append([*briefcase, "package", target, "-p", package_format or "debug-apk"])
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
        package_format = package_format or "debug-apk"
        suffixes = [".aab"] if package_format == "aab" else [".apk"]
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

    if target == "android":
        candidates = _prefer_android_artifact(candidates, package_format or "debug-apk")

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _prefer_android_artifact(candidates: list[Path], package_format: str) -> list[Path]:
    if package_format == "debug-apk":
        preferred = [path for path in candidates if _is_debug_apk(path)]
    elif package_format == "apk":
        preferred = [path for path in candidates if not _is_debug_apk(path)]
    else:
        preferred = []

    return preferred or candidates


def _is_debug_apk(path: Path) -> bool:
    return path.suffix.lower() == ".apk" and any("debug" in part.lower() for part in path.parts)


def _insert_before(document: str, marker: str, content: str, fallback_before: str | None = None) -> str:
    lower = document.lower()
    index = lower.rfind(marker.lower())
    if index == -1 and fallback_before:
        index = lower.rfind(fallback_before.lower())
    if index == -1:
        return f"{document}\n{content}"
    return f"{document[:index]}{content}{document[index:]}"


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
