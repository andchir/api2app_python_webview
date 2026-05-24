"""Helpers for converting non-ASCII names (e.g. Russian) into safe
identifiers used by Briefcase pyproject fields and the artifact filenames
returned by the API."""

from __future__ import annotations

import re
import unicodedata


CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}

DEFAULT_BUNDLE = "com.api2app.generated"
DEFAULT_APP_SLUG = "app"


def transliterate(text: str) -> str:
    """Convert Cyrillic letters to Latin equivalents and strip diacritics.

    Other Unicode characters are passed through NFKD normalisation so common
    accents (German umlauts, French accents, etc.) are reduced to ASCII.
    Control and formatting code points (zero-width spaces, BOM, etc.) are
    discarded because they tend to break TOML/Briefcase identifiers.
    """

    if not text:
        return ""

    pieces: list[str] = []
    for char in text:
        if unicodedata.category(char).startswith("C"):
            if char.isspace():
                pieces.append(" ")
            continue
        lower = char.lower()
        mapping = CYRILLIC_TO_LATIN.get(lower)
        if mapping is None:
            pieces.append(char)
            continue
        if char.isupper() and mapping:
            mapping = mapping[0].upper() + mapping[1:]
        pieces.append(mapping)

    normalized = unicodedata.normalize("NFKD", "".join(pieces))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def slugify_filename(text: str, default: str = DEFAULT_APP_SLUG) -> str:
    """Return an ASCII filename-safe slug derived from ``text``."""

    transliterated = transliterate(text)
    ascii_only = transliterated.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_only).strip("-._")
    return slug or default


def slugify_bundle_segment(text: str, default: str = DEFAULT_APP_SLUG) -> str:
    """Return a DNS-safe bundle segment (lowercase ASCII letters and digits).

    Segments must start with an ASCII letter to satisfy Android applicationId
    requirements, so a leading digit is prefixed with ``a``.
    """

    transliterated = transliterate(text).lower()
    ascii_only = transliterated.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "", ascii_only)
    if not slug:
        return default
    if not slug[0].isalpha():
        slug = "a" + slug
    return slug


def normalize_bundle(
    bundle: str | None,
    app_name: str | None,
    *,
    default_bundle: str = DEFAULT_BUNDLE,
) -> str:
    """Transliterate ``bundle`` segments and append an app-specific suffix
    when the bundle is missing or still equal to the project default. This
    keeps Briefcase happy (ASCII identifiers) and avoids different generated
    applications colliding on the same Android applicationId."""

    raw_parts = [part.strip() for part in (bundle or "").split(".")]
    cleaned_parts = [slugify_bundle_segment(part) for part in raw_parts if part]
    cleaned = ".".join(cleaned_parts)

    if not cleaned:
        cleaned = default_bundle

    if cleaned == default_bundle:
        suffix = slugify_bundle_segment(app_name or "", default=DEFAULT_APP_SLUG)
        cleaned = f"{default_bundle}.{suffix}"

    return cleaned


def sanitize_display_text(text: str | None, default: str = "") -> str:
    """Strip control characters and collapse whitespace for values that go
    directly into TOML (formal_name, description, version)."""

    if not text:
        return default

    cleaned_chars: list[str] = []
    for ch in text:
        if unicodedata.category(ch).startswith("C"):
            if ch.isspace():
                cleaned_chars.append(" ")
            continue
        cleaned_chars.append(ch)
    cleaned = " ".join("".join(cleaned_chars).split())
    return cleaned or default


def artifact_basename(
    app_name: str | None,
    version: str | None,
    *,
    default_app: str = DEFAULT_APP_SLUG,
    default_version: str = "0.0.1",
) -> str:
    """Return ``{app_slug}-{version}`` using ASCII-only characters."""

    app_slug = slugify_filename(app_name or "", default=default_app)
    version_slug = slugify_filename(version or "", default=default_version)
    return f"{app_slug}-{version_slug}"
