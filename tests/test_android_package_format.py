from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError
from starlette.datastructures import FormData

from build_api.builder import (
    APP_TEMPLATE,
    _build_commands,
    _find_artifact,
    _install_created_app_resources,
    _native_app_config,
    _patch_pyproject,
    _stored_log_path,
    _write_icons,
    compose_html,
)
from build_api.main import _form_openapi_extra, _payload_from_form
from build_api.schemas import AndroidBuildRequest


HTML = "<!doctype html><html><head></head><body></body></html>"


class FakeRequest:
    def __init__(self, form: FormData):
        self._form = form

    async def form(self) -> FormData:
        return self._form


def test_android_request_defaults_to_debug_apk() -> None:
    request = AndroidBuildRequest(html=HTML)

    assert request.package_format == "debug-apk"


def test_android_request_accepts_only_known_formats() -> None:
    assert AndroidBuildRequest(html=HTML, package_format="debug-apk").package_format == "debug-apk"
    assert AndroidBuildRequest(html=HTML, package_format="aab").package_format == "aab"

    with pytest.raises(ValidationError):
        AndroidBuildRequest(html=HTML, package_format="zip")


def test_android_form_payload_defaults_to_debug_apk() -> None:
    payload, assets_dir = asyncio.run(
        _payload_from_form(FakeRequest(FormData({"html": HTML})), AndroidBuildRequest)
    )

    assert assets_dir is None
    assert payload["package_format"] == "debug-apk"


def test_android_form_payload_accepts_aab() -> None:
    payload, _assets_dir = asyncio.run(
        _payload_from_form(
            FakeRequest(FormData({"html": HTML, "package_format": "aab"})),
            AndroidBuildRequest,
        )
    )

    assert payload["package_format"] == "aab"


def test_icon_file_fields_ignore_non_file_values() -> None:
    payload, assets_dir = asyncio.run(
        _payload_from_form(
            FakeRequest(FormData({"html": HTML, "icon_file": "", "ico_file": "not-a-file"})),
            AndroidBuildRequest,
        )
    )

    assert assets_dir is None
    assert "icon" not in payload


def test_android_openapi_includes_package_format() -> None:
    extra = _form_openapi_extra(include_android_format=True)
    properties = extra["requestBody"]["content"]["multipart/form-data"]["schema"][
        "properties"
    ]

    assert properties["package_format"] == {
        "type": "string",
        "enum": ["debug-apk", "apk", "aab"],
        "default": "debug-apk",
    }


def test_android_package_command_uses_requested_format() -> None:
    settings = SimpleNamespace(briefcase_command=("briefcase",))

    commands = _build_commands(settings, "android", "aab")

    assert commands[-1] == ["briefcase", "package", "android", "-p", "aab"]


def test_android_package_command_defaults_to_debug_apk() -> None:
    settings = SimpleNamespace(briefcase_command=("briefcase",))

    commands = _build_commands(settings, "android", None)

    assert commands[-1] == ["briefcase", "package", "android", "-p", "debug-apk"]


def test_android_artifact_search_uses_requested_suffix(tmp_path) -> None:
    apk = tmp_path / "app-release.apk"
    aab = tmp_path / "app-release.aab"
    apk.write_text("apk", encoding="utf-8")
    aab.write_text("aab", encoding="utf-8")

    assert _find_artifact(tmp_path, "android", "aab") == aab
    assert _find_artifact(tmp_path, "android", "apk") == apk


def test_android_artifact_search_defaults_to_debug_apk(tmp_path) -> None:
    release_dir = tmp_path / "dist"
    debug_dir = tmp_path / "build" / "outputs" / "apk" / "debug"
    release_dir.mkdir()
    debug_dir.mkdir(parents=True)
    release = release_dir / "app-release.apk"
    debug = debug_dir / "app-debug.apk"
    debug.write_text("debug", encoding="utf-8")
    release.write_text("release", encoding="utf-8")

    assert _find_artifact(tmp_path, "android", None) == debug
    assert _find_artifact(tmp_path, "android", "debug-apk") == debug


def test_stored_log_path_copies_briefcase_log_from_wrapper_output(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    artifact_dir = tmp_path / "artifacts"
    real_log = workspace / "logs" / "briefcase.2026_05_23-18_03_09.build.log"
    wrapper_log = artifact_dir / "build.log"
    real_log.parent.mkdir(parents=True)
    artifact_dir.mkdir()
    real_log.write_text("briefcase details", encoding="utf-8")
    wrapper_log.write_text(f"Saving log... done\nLog saved to {real_log}\n", encoding="utf-8")

    stored_path = _stored_log_path(wrapper_log, workspace, artifact_dir)

    assert stored_path == artifact_dir / real_log.name
    assert stored_path.read_text(encoding="utf-8") == "briefcase details"


def test_stored_log_path_falls_back_to_wrapper_log(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    artifact_dir = tmp_path / "artifacts"
    wrapper_log = artifact_dir / "build.log"
    workspace.mkdir()
    artifact_dir.mkdir()
    wrapper_log.write_text("no briefcase log here", encoding="utf-8")

    assert _stored_log_path(wrapper_log, workspace, artifact_dir) == wrapper_log


def test_generated_app_template_loads_packaged_html_resource() -> None:
    compile(APP_TEMPLATE, "generated_app.py", "exec")

    assert "resources.files(__package__)" in APP_TEMPLATE
    assert "loadDataWithBaseURL" in APP_TEMPLATE


def test_generated_app_template_uses_native_menu_commands() -> None:
    compile(APP_TEMPLATE, "generated_app.py", "exec")

    assert "toga.Command" in APP_TEMPLATE
    assert "toga.Group" in APP_TEMPLATE
    assert "self.commands.add" in APP_TEMPLATE
    assert "self.main_window.toolbar" not in APP_TEMPLATE


def test_generated_app_template_disables_android_webview_zoom() -> None:
    compile(APP_TEMPLATE, "generated_app.py", "exec")

    assert "setUseWideViewPort" in APP_TEMPLATE
    assert "setLoadWithOverviewMode" in APP_TEMPLATE
    assert "_configure_webview_zoom(webview)" in APP_TEMPLATE
    assert "setSupportZoom" in APP_TEMPLATE
    assert "setBuiltInZoomControls" in APP_TEMPLATE
    assert "setDisplayZoomControls" in APP_TEMPLATE
    assert "setTextZoom" in APP_TEMPLATE
    assert "setInitialScale" in APP_TEMPLATE


def test_compose_html_adds_mobile_viewport() -> None:
    document = compose_html({"html": HTML})

    assert (
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        in document
    )


def test_compose_html_keeps_existing_viewport() -> None:
    html = (
        '<!doctype html><html><head><meta name="viewport" content="width=420"></head>'
        "<body></body></html>"
    )

    document = compose_html({"html": html})

    assert document.count('name="viewport"') == 1
    assert 'content="width=420"' in document


def test_compose_html_does_not_inject_header_or_menu_markup() -> None:
    document = compose_html(
        {
            "html": HTML,
            "css": "body { color: red; }",
            "js": "window.loaded = true;",
            "app_name": "Native App",
            "header": {"enabled": True, "title": "Native Header"},
            "menu": {
                "enabled": True,
                "position": "top",
                "items": [{"label": "Native Menu", "href": "#native"}],
            },
        }
    )

    assert "api2app-header" not in document
    assert "api2app-menu" not in document
    assert "Native Header" not in document
    assert "Native Menu" not in document
    assert "body { color: red; }" in document
    assert "window.loaded = true;" in document


def test_native_app_config_keeps_header_and_menu() -> None:
    request = {
        "app_name": "Native App",
        "header": {"enabled": True, "title": "Native Header"},
        "menu": {"enabled": True, "items": [{"label": "Home", "href": "#home"}]},
    }

    assert _native_app_config(request) == request


def test_uploaded_icon_generates_android_launcher_and_splash(tmp_path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (512, 512), (255, 0, 0, 255)).save(source)

    workspace = tmp_path / "workspace"
    _write_icons(workspace, {"icon": {"source_path": str(source)}})

    android_resources = workspace / "src" / "api2app" / "resources" / "android"
    launcher = Image.open(android_resources / "mipmap-mdpi" / "ic_launcher.png")
    foreground = Image.open(android_resources / "mipmap-mdpi" / "ic_launcher_foreground.png")
    splash = Image.open(android_resources / "mipmap-mdpi" / "splash.png").convert("RGBA")
    briefcase_icon = workspace / "resources" / "generated" / "icon"

    assert launcher.size == (48, 48)
    assert foreground.size == (108, 108)
    assert splash.size == (320, 320)
    assert splash.getchannel("A").getbbox() == (64, 64, 256, 256)
    assert (android_resources / "mipmap-xxxhdpi" / "splash.png").exists()
    assert (workspace / "src" / "api2app" / "resources" / "icon.ico").exists()
    assert Image.open(briefcase_icon.with_name("icon-square-48.png")).size == (48, 48)
    assert Image.open(briefcase_icon.with_name("icon-adaptive-108.png")).size == (108, 108)
    assert Image.open(briefcase_icon.with_name("icon-square-320.png")).size == (320, 320)
    assert briefcase_icon.with_suffix(".ico").exists()


def test_uploaded_icon_is_declared_for_briefcase_android_resources(tmp_path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (512, 512), (0, 255, 0, 255)).save(source)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        (Path(__file__).parents[1] / "api2app" / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    _patch_pyproject(pyproject, {"icon": {"source_path": str(source)}})

    assert 'icon = "resources/generated/icon"' in pyproject.read_text(encoding="utf-8")


def test_generated_android_icons_are_copied_into_created_gradle_project(tmp_path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (512, 512), (0, 0, 255, 255)).save(source)
    workspace = tmp_path / "workspace"
    gradle_res = workspace / "build" / "api2app" / "android" / "gradle" / "app" / "src" / "main" / "res"
    gradle_res.mkdir(parents=True)
    _write_icons(workspace, {"icon": {"source_path": str(source)}})

    log = StringIO()
    _install_created_app_resources(workspace, {"icon": {"source_path": str(source)}}, "android", log)

    launcher = Image.open(gradle_res / "mipmap-mdpi" / "ic_launcher.png")
    foreground = Image.open(gradle_res / "mipmap-mdpi" / "ic_launcher_foreground.png")
    splash = Image.open(gradle_res / "mipmap-mdpi" / "splash.png")

    assert launcher.size == (48, 48)
    assert foreground.size == (108, 108)
    assert splash.size == (320, 320)
    assert "generated Android icon resources" in log.getvalue()
