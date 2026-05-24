"""Internationalization support for the build API.

Language is resolved from the ``Accept-Language`` request header.
Default language is Russian (``ru``).  English (``en``) is also supported.

Usage
-----
In middleware, call ``set_language(lang)`` at the start of each request.
Everywhere else call ``t("key", field="html", limit=1024)`` to get the
translated string for the current request language.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_current_lang: ContextVar[str] = ContextVar("_current_lang", default="ru")

SUPPORTED_LANGUAGES = {"ru", "en"}
DEFAULT_LANGUAGE = "ru"


# ---------------------------------------------------------------------------
# Language negotiation
# ---------------------------------------------------------------------------

def parse_accept_language(accept_language: str | None) -> str:
    """Return the best supported language from an ``Accept-Language`` header.

    Returns ``DEFAULT_LANGUAGE`` when the header is absent, ``*``, or names
    only languages we do not support.
    """
    if not accept_language or accept_language.strip() == "*":
        return DEFAULT_LANGUAGE

    candidates: list[tuple[str, float]] = []
    for part in accept_language.split(","):
        part = part.strip()
        if ";q=" in part:
            lang_tag, q_str = part.rsplit(";q=", 1)
            try:
                q = float(q_str.strip())
            except ValueError:
                q = 1.0
        else:
            lang_tag, q = part, 1.0
        lang_tag = lang_tag.strip().lower()
        if lang_tag:
            candidates.append((lang_tag, q))

    candidates.sort(key=lambda x: x[1], reverse=True)

    for lang_tag, _ in candidates:
        if lang_tag in SUPPORTED_LANGUAGES:
            return lang_tag
        prefix = lang_tag.split("-")[0]
        if prefix in SUPPORTED_LANGUAGES:
            return prefix

    return DEFAULT_LANGUAGE


def set_language(lang: str) -> None:
    """Store *lang* in the current async context (call from middleware)."""
    _current_lang.set(lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE)


def current_language() -> str:
    """Return the language for the current request context."""
    return _current_lang.get()


# ---------------------------------------------------------------------------
# Translation tables
# ---------------------------------------------------------------------------

# HTTP-level error messages (raised as HTTPException)
_HTTP_MESSAGES: dict[str, dict[str, str]] = {
    # Auth
    "api_key_not_configured": {
        "en": "BUILD_API_KEY is not configured",
        "ru": "BUILD_API_KEY не настроен",
    },
    "invalid_api_key": {
        "en": "Invalid or missing API key",
        "ru": "Неверный или отсутствующий API-ключ",
    },
    # Jobs
    "job_not_found": {
        "en": "Job not found",
        "ru": "Задача не найдена",
    },
    "job_not_found_or_not_finished": {
        "en": "Job not found or not finished yet",
        "ru": "Задача не найдена или ещё не завершена",
    },
    "job_result_expired": {
        "en": "Job result expired",
        "ru": "Результат задачи устарел",
    },
    "build_not_completed": {
        "en": "Build is not completed",
        "ru": "Сборка не завершена",
    },
    "artifact_not_found": {
        "en": "Artifact file not found",
        "ru": "Файл артефакта не найден",
    },
    "log_not_found": {
        "en": "Log file not found",
        "ru": "Файл лога не найден",
    },
    # Form field errors
    "field_must_be_form_not_file": {
        "en": "{field} must be a form field, not a file",
        "ru": "{field} должен быть текстовым полем формы, а не файлом",
    },
    "field_required": {
        "en": "Missing required form field: {field}",
        "ru": "Обязательное поле формы отсутствует: {field}",
    },
    "field_must_be_boolean": {
        "en": "{field} must be a boolean value",
        "ru": "{field} должен быть булевым значением (true/false)",
    },
    "field_must_be_file": {
        "en": "{field} must be a file field",
        "ru": "{field} должен быть полем для загрузки файла",
    },
    "field_must_be_json_object": {
        "en": "{field} must be a valid JSON object",
        "ru": "{field} должен быть корректным JSON-объектом",
    },
    "field_not_json_object": {
        "en": "{field} must be a JSON object",
        "ru": "{field} должен быть JSON-объектом",
    },
    # Menu
    "menu_items_invalid_json": {
        "en": "menu_items must be a valid JSON array",
        "ru": "menu_items должен быть корректным JSON-массивом",
    },
    "menu_items_not_array": {
        "en": "menu_items must be a JSON array",
        "ru": "menu_items должен быть JSON-массивом",
    },
    # Icon mutual exclusion
    "icon_file_and_url": {
        "en": "Use either icon_file or icon_url, not both",
        "ru": "Укажите либо icon_file, либо icon_url, но не оба сразу",
    },
    "ico_file_and_url": {
        "en": "Use either ico_file or ico_url, not both",
        "ru": "Укажите либо ico_file, либо ico_url, но не оба сразу",
    },
    # Image upload / download errors
    "image_too_large": {
        "en": "{field} is too large: limit is {limit} bytes",
        "ru": "{field} слишком большой: лимит составляет {limit} байт",
    },
    "image_empty": {
        "en": "{field} is empty",
        "ru": "{field} пустой",
    },
    "image_must_be_http_url": {
        "en": "{field} must be an http or https URL",
        "ru": "{field} должен быть http- или https-URL",
    },
    "image_download_failed": {
        "en": "Could not download {field}: {exc}",
        "ru": "Не удалось загрузить {field}: {exc}",
    },
    "image_url_not_image": {
        "en": "{field} URL must return an image",
        "ru": "URL {field} должен возвращать изображение",
    },
    "image_url_empty": {
        "en": "{field} URL returned an empty file",
        "ru": "URL {field} вернул пустой файл",
    },
    "image_invalid": {
        "en": "{field} must be a valid image file",
        "ru": "{field} должен быть корректным файлом изображения",
    },
    "image_zero_dimensions": {
        "en": "{field} must have non-zero dimensions",
        "ru": "{field} должен иметь ненулевые размеры",
    },
    # System / dependencies
    "missing_multipart": {
        "en": "python-multipart is required for form uploads. Install requirements.txt.",
        "ru": "Для загрузки форм требуется python-multipart. Установите зависимости из requirements.txt.",
    },
    "missing_pillow": {
        "en": "Pillow is required to validate image uploads. Install requirements.txt.",
        "ru": "Для проверки изображений требуется Pillow. Установите зависимости из requirements.txt.",
    },
    # Source payload size
    "source_too_large": {
        "en": "Source payload is too large: {total} bytes, limit is {limit} bytes",
        "ru": "Исходные данные слишком большие: {total} байт, лимит {limit} байт",
    },
}


# Pydantic validation error type → translated message template.
# Templates may use ctx keys that Pydantic includes in the error dict.
_PYDANTIC_TYPES: dict[str, dict[str, str]] = {
    "missing": {
        "en": "Field required",
        "ru": "Поле обязательно для заполнения",
    },
    "string_too_short": {
        "en": "String should have at least {min_length} character(s)",
        "ru": "Строка должна содержать не менее {min_length} символа(-ов)",
    },
    "string_too_long": {
        "en": "String should have at most {max_length} character(s)",
        "ru": "Строка должна содержать не более {max_length} символа(-ов)",
    },
    "literal_error": {
        "en": "Input should be {expected}",
        "ru": "Допустимые значения: {expected}",
    },
    "string_type": {
        "en": "Input should be a valid string",
        "ru": "Значение должно быть строкой",
    },
    "bool_type": {
        "en": "Input should be a valid boolean",
        "ru": "Значение должно быть булевым (true/false)",
    },
    "int_type": {
        "en": "Input should be a valid integer",
        "ru": "Значение должно быть целым числом",
    },
    "list_type": {
        "en": "Input should be a valid list",
        "ru": "Значение должно быть списком",
    },
    "value_error": {
        # Custom application errors (e.g. HTML validation).
        # The original English message is preserved in the "msg" field;
        # for Russian we strip Pydantic's "Value error, " prefix and
        # translate known HTML sub-messages (see _translate_html_msg).
        "en": "{msg}",
        "ru": "{msg}",
    },
}

# Sub-message translations for HTML document validation errors
# (raised by builder.validate_html_document).
_HTML_SUB_MESSAGES: dict[str, str] = {
    "must start with <!doctype html>": (
        "должен начинаться с <!doctype html>"
    ),
    "must have an opening <html> tag immediately after <!doctype html>": (
        "должен содержать открывающий тег <html> сразу после <!doctype html>"
    ),
    "must end with </html>": "должен заканчиваться на </html>",
    "must include an opening <head> tag": (
        "должен содержать открывающий тег <head>"
    ),
    "must include a closing </head> tag": (
        "должен содержать закрывающий тег </head>"
    ),
    "must include an opening <body> tag": (
        "должен содержать открывающий тег <body>"
    ),
    "must include a closing </body> tag": (
        "должен содержать закрывающий тег </body>"
    ),
    "<head> must be closed after it is opened": (
        "<head> должен быть закрыт после открытия"
    ),
    "<body> must be closed after it is opened": (
        "<body> должен быть закрыт после открытия"
    ),
    "<head> must be closed before <body> starts": (
        "<head> должен быть закрыт до начала <body>"
    ),
    "</body> must appear before </html>": (
        "</body> должен стоять перед </html>"
    ),
}

_HTML_VALIDATION_PREFIX_EN = "Invalid HTML document: "
_HTML_VALIDATION_PREFIX_RU = "Некорректный HTML-документ: "


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    """Return the translated string for *key* in *lang* (or current language).

    Unknown ``kwargs`` are silently ignored so callers don't need to guard
    against missing placeholders.
    """
    resolved = lang if lang in SUPPORTED_LANGUAGES else current_language()
    entry = _HTTP_MESSAGES.get(key)
    if entry is None:
        return key
    template = entry.get(resolved) or entry.get(DEFAULT_LANGUAGE) or key
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


def translate_pydantic_errors(errors: list[dict[str, Any]], lang: str | None = None) -> list[dict[str, Any]]:
    """Return a copy of *errors* with ``msg`` fields translated to *lang*.

    Each item in *errors* should be a Pydantic error dict with at least
    ``type`` and ``msg`` keys (the format returned by ``ValidationError.errors()``).
    """
    resolved = lang if lang in SUPPORTED_LANGUAGES else current_language()
    result = []
    for error in errors:
        error = dict(error)
        error_type = error.get("type", "")
        original_msg: str = error.get("msg", "")
        ctx: dict[str, Any] = error.get("ctx") or {}

        type_entry = _PYDANTIC_TYPES.get(error_type)
        if type_entry is None:
            result.append(error)
            continue

        if resolved == "en":
            # Keep Pydantic's default English message unchanged.
            result.append(error)
            continue

        template = type_entry.get(resolved) or type_entry.get("en") or original_msg

        if error_type == "value_error":
            error["msg"] = _translate_value_error_msg(original_msg, resolved)
        else:
            flat_ctx = _flatten_ctx(ctx)
            try:
                error["msg"] = template.format(**flat_ctx)
            except (KeyError, ValueError):
                error["msg"] = template

        result.append(error)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flatten_ctx(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return a flat dict of context values suitable for str.format()."""
    flat: dict[str, Any] = {}
    for k, v in ctx.items():
        if isinstance(v, Exception):
            flat[k] = str(v)
        else:
            flat[k] = v
    return flat


def _translate_value_error_msg(msg: str, lang: str) -> str:
    """Translate a Pydantic value_error message to *lang*.

    Pydantic v2 prefixes the message with ``"Value error, "``.  We strip
    that, check whether the remainder looks like an HTML validation error,
    and translate the individual sub-messages when possible.
    """
    if lang == "en":
        return msg

    # Strip Pydantic's "Value error, " prefix.
    body = msg
    if body.startswith("Value error, "):
        body = body[len("Value error, "):]

    # Handle HTML validation errors from builder.validate_html_document.
    if body.startswith(_HTML_VALIDATION_PREFIX_EN):
        raw_subs = body[len(_HTML_VALIDATION_PREFIX_EN):]
        subs = [s.strip() for s in raw_subs.split(";")]
        translated_subs = [
            _HTML_SUB_MESSAGES.get(s, s) for s in subs
        ]
        return _HTML_VALIDATION_PREFIX_RU + "; ".join(translated_subs)

    return body
