from __future__ import annotations

from pathlib import Path

from build_api.builder import _artifact_filename, _patch_pyproject
from build_api.translit import (
    DEFAULT_BUNDLE,
    artifact_basename,
    normalize_bundle,
    sanitize_display_text,
    slugify_bundle_segment,
    slugify_filename,
    transliterate,
)


def test_transliterate_converts_cyrillic_letters_to_latin() -> None:
    assert transliterate("Привет, мир!") == "Privet, mir!"
    assert transliterate("Ёжик ходит") == "Yozhik hodit"
    assert transliterate("Щука") == "Shchuka"


def test_transliterate_preserves_ascii() -> None:
    assert transliterate("Hello world 123") == "Hello world 123"
    assert transliterate("") == ""


def test_transliterate_strips_diacritics() -> None:
    assert transliterate("café") == "cafe"
    assert transliterate("Über") == "Uber"


def test_transliterate_drops_zero_width_characters_and_keeps_word_boundaries() -> None:
    assert transliterate("Hello\u200bWorld") == "HelloWorld"
    assert transliterate("Demo\ufeff") == "Demo"
    assert transliterate("Line1\nLine2") == "Line1 Line2"
    assert transliterate("Col1\tCol2") == "Col1 Col2"


def test_slugify_filename_replaces_unsafe_characters() -> None:
    assert slugify_filename("Моё приложение") == "Moyo-prilozhenie"
    assert slugify_filename("Demo App 2.0") == "Demo-App-2.0"


def test_slugify_filename_falls_back_to_default() -> None:
    assert slugify_filename("", default="app") == "app"
    assert slugify_filename("???", default="app") == "app"


def test_slugify_filename_strips_quotes_and_punctuation() -> None:
    assert slugify_filename('My "App"') == "My-App"
    assert slugify_filename("Don't Stop!") == "Don-t-Stop"
    assert slugify_filename("«Демо»") == "Demo"
    assert slugify_filename("«Моё» «Приложение»") == "Moyo-Prilozhenie"
    assert slugify_filename("App/Name\\Test") == "App-Name-Test"
    assert slugify_filename("App<>:|?*Name") == "App-Name"


def test_slugify_bundle_segment_returns_dns_safe_slug() -> None:
    assert slugify_bundle_segment("Моё приложение") == "moyoprilozhenie"
    assert slugify_bundle_segment("Demo App!") == "demoapp"


def test_slugify_bundle_segment_prefixes_letter_if_starts_with_digit() -> None:
    assert slugify_bundle_segment("2024 app") == "a2024app"


def test_slugify_bundle_segment_falls_back_to_default() -> None:
    assert slugify_bundle_segment("", default="app") == "app"
    assert slugify_bundle_segment("???", default="app") == "app"


def test_slugify_bundle_segment_strips_quotes_and_punctuation() -> None:
    assert slugify_bundle_segment('My "App"!') == "myapp"
    assert slugify_bundle_segment("«Моё приложение»") == "moyoprilozhenie"
    assert slugify_bundle_segment("Don't-Stop") == "dontstop"


def test_normalize_bundle_appends_app_suffix_to_default_bundle() -> None:
    bundle = normalize_bundle(DEFAULT_BUNDLE, "Моё приложение")

    assert bundle == f"{DEFAULT_BUNDLE}.moyoprilozhenie"


def test_normalize_bundle_appends_app_suffix_when_bundle_is_missing() -> None:
    assert normalize_bundle(None, "Demo App") == f"{DEFAULT_BUNDLE}.demoapp"
    assert normalize_bundle("", "Demo App") == f"{DEFAULT_BUNDLE}.demoapp"


def test_normalize_bundle_transliterates_user_provided_bundle() -> None:
    bundle = normalize_bundle("ru.моя.компания", "Demo App")

    assert bundle == "ru.moya.kompaniya"


def test_normalize_bundle_keeps_unique_user_bundle_unchanged() -> None:
    assert normalize_bundle("ru.example.myapp", "Demo App") == "ru.example.myapp"


def test_artifact_basename_uses_transliterated_app_name() -> None:
    assert artifact_basename("Моё приложение", "1.2.3") == "Moyo-prilozhenie-1.2.3"


def test_artifact_basename_falls_back_to_defaults() -> None:
    assert artifact_basename("", "") == "app-0.0.1"


def test_artifact_basename_strips_quotes() -> None:
    assert artifact_basename('"Моё приложение"', "1.0") == "Moyo-prilozhenie-1.0"


def test_sanitize_display_text_keeps_quotes_but_drops_control_chars() -> None:
    assert sanitize_display_text('My "App"') == 'My "App"'
    assert sanitize_display_text("Line 1\nLine 2") == "Line 1 Line 2"
    assert sanitize_display_text("Demo\u200b\ufeffApp") == "DemoApp"
    assert sanitize_display_text("   Hello   World   ") == "Hello World"


def test_sanitize_display_text_falls_back_to_default() -> None:
    assert sanitize_display_text("", default="fallback") == "fallback"
    assert sanitize_display_text(None, default="fallback") == "fallback"
    assert sanitize_display_text("\u200b\ufeff", default="fallback") == "fallback"


def _read_pyproject_template() -> str:
    return (Path(__file__).parents[1] / "api2app" / "pyproject.toml").read_text(encoding="utf-8")


def test_patch_pyproject_transliterates_bundle_and_project_name(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_read_pyproject_template(), encoding="utf-8")

    _patch_pyproject(pyproject, {"app_name": "Моё приложение", "version": "1.2.3"})

    text = pyproject.read_text(encoding="utf-8")
    assert 'project_name = "Moyo-prilozhenie"' in text
    assert f'bundle = "{DEFAULT_BUNDLE}.moyoprilozhenie"' in text
    assert 'formal_name = "Моё приложение"' in text


def test_patch_pyproject_makes_empty_bundle_unique_for_each_app(tmp_path) -> None:
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text(_read_pyproject_template(), encoding="utf-8")
    second.write_text(_read_pyproject_template(), encoding="utf-8")

    _patch_pyproject(first, {"app_name": "First App", "bundle": ""})
    _patch_pyproject(second, {"app_name": "Second App", "bundle": ""})

    first_text = first.read_text(encoding="utf-8")
    second_text = second.read_text(encoding="utf-8")

    assert f'bundle = "{DEFAULT_BUNDLE}.firstapp"' in first_text
    assert f'bundle = "{DEFAULT_BUNDLE}.secondapp"' in second_text


def test_patch_pyproject_makes_missing_bundle_unique_for_each_app(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_read_pyproject_template(), encoding="utf-8")

    _patch_pyproject(pyproject, {"app_name": "Моё приложение"})

    assert f'bundle = "{DEFAULT_BUNDLE}.moyoprilozhenie"' in pyproject.read_text(encoding="utf-8")


def test_patch_pyproject_keeps_user_supplied_bundle(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_read_pyproject_template(), encoding="utf-8")

    _patch_pyproject(pyproject, {"app_name": "Demo", "bundle": "org.example.myapp"})

    assert 'bundle = "org.example.myapp"' in pyproject.read_text(encoding="utf-8")


def test_patch_pyproject_strips_quotes_and_newlines_from_input(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_read_pyproject_template(), encoding="utf-8")

    _patch_pyproject(
        pyproject,
        {
            "app_name": '«Моё»\n"приложение"',
            "version": "1.0\nbeta",
            "description": "Hello\nWorld\u200b!",
        },
    )

    text = pyproject.read_text(encoding="utf-8")
    assert 'project_name = "Moyo-prilozhenie"' in text
    assert f'bundle = "{DEFAULT_BUNDLE}.moyoprilozhenie"' in text
    assert 'version = "1.0-beta"' in text
    assert 'description = "Hello World!"' in text
    assert 'formal_name = "«Моё» \\"приложение\\""' in text
    assert "\n" not in [line for line in text.splitlines() if line.startswith("formal_name")][0]


def test_artifact_filename_uses_transliterated_app_name() -> None:
    request = {"app_name": "Моё приложение", "version": "0.0.2"}

    assert _artifact_filename(request, ".apk") == "Moyo-prilozhenie-0.0.2.apk"


def test_artifact_filename_falls_back_to_defaults() -> None:
    assert _artifact_filename({}, ".msi") == "api2app-generated-0.0.1.msi"
