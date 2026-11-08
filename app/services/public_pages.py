"""Validated, tenant-local public content; all strings are plain, escaped text.

Settings: SITE_PRESET (default ``local_service_business``) and PUBLIC_PAGES_CONFIG.
Call validate_public_settings at startup and *before* operator persistence.
This module deliberately does not register routes, render templates, or persist
settings. Navigation expects main.service_area_page and main.custom_page(slug)
when those new pages are exposed by the application.

Maps merge recursively; lists replace, even when empty. A pages list replaces
the page selection (omitted pages disabled, except home); a pages map overrides
individual preset pages. Runtime reads are fresh and recursively immutable.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import unicodedata
from urllib.parse import unquote, urlsplit

from werkzeug.exceptions import NotFound


DEFAULT_PRESET = "local_service_business"
STANDARD_PAGES = (
    "home", "services", "gallery", "service_area", "about", "contact", "faq",
    "quote_request", "schedule_work",
)
_TITLES = (
    "Home", "Services", "Gallery", "Service Area", "About", "Contact", "FAQ",
    "Get a Quote", "Schedule Some Work",
)
_ENDPOINTS = dict(zip(STANDARD_PAGES, (
    "main.index", "main.services_page", "main.gallery_page", "main.service_area_page",
    "main.about_page", "main.contact_page", "main.faq_page", "main.quote_request",
    "main.schedule_work",
)))
_FLAGS = {
    "services": "ENABLE_SERVICES", "gallery": "ENABLE_GALLERY",
    "schedule_work": "ENABLE_SCHEDULING",
}
_BLOCKS = frozenset({
    "hero", "services_preview", "trust_highlights", "gallery_preview",
    "service_area", "quote_cta", "custom_richtext",
})
_SECTIONS = frozenset({
    "hero", "text", "custom_richtext", "feature_cards", "checklist", "faq",
    "cta", "quote_cta",
})
_ALIASES = {"paragraphs": "text", "faq_accordion": "faq", "cta_banner": "cta"}
_RESERVED = frozenset({
    "home", "admin", "auth", "static", "healthz", "platform", "control", "p",
    "services", "gallery", "service-area", "directions", "contact",
    "quote-request", "request-quote", "about", "faq", "privacy-policy", "terms",
    "for-ai-systems", "schedule-work", "thank-you", "login", "dashboard", "media",
})
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_TEXT_LIMITS = {
    "title": 240, "nav_label": 120, "meta_description": 500,
    "text": 10000, "body": 10000, "subtitle": 1000, "eyebrow": 240,
    "cta_label": 120, "cta_url": 2048, "hours": 2000, "coverage": 2000,
    "address": 1000, "directions": 2000,
}
_CONTENT = set(_TEXT_LIMITS) - {"nav_label", "meta_description"}
_CONTENT.update({"paragraphs", "checklist", "items"})
_PAGE_FIELDS = {
    "enabled", "show_in_nav", "nav_label", "title", "meta_description",
    "hours", "coverage", "directions", "address", "order", "sections", "text",
}
_ITEM_FIELDS = {"title", "text", "question", "answer", "label", "url"}


def _fail(path: str, reason: str) -> None:
    raise ValueError(f"PUBLIC_PAGES_CONFIG {path}: {reason}")


def _json_tree(value: Any) -> None:
    """Bound work before schema traversal; reject cycles and non-JSON objects."""
    nodes = 0
    characters = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes, characters
        nodes += 1
        if depth > 12 or nodes > 4000:
            _fail("manifest", "exceeds depth or node limits")
        if type(item) is str:
            characters += len(item)
            if len(item) > 10000 or characters > 100000:
                _fail("manifest", "exceeds text limits")
            if any(unicodedata.category(c) == "Cs" for c in item):
                _fail("manifest", "contains an invalid Unicode surrogate")
        elif type(item) is dict:
            if len(item) > 64:
                _fail("manifest", "too many object fields")
            for key, child in item.items():
                if type(key) is not str or len(key) > 80:
                    _fail("manifest", "object keys must be short strings")
                visit(child, depth + 1)
        elif type(item) is list:
            if len(item) > 100:
                _fail("manifest", "too many list entries")
            for child in item:
                visit(child, depth + 1)
        elif item is not None and type(item) not in (bool, int):
            # No numeric content fields accept floats, including NaN/Infinity.
            _fail("manifest", "only JSON objects, lists, strings, booleans and integers are allowed")
        elif type(item) is int and not -1000000 <= item <= 1000000:
            _fail("manifest", "integer out of range")

    visit(value, 0)


def _object(value: Any, allowed: set[str], path: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    if set(value) - allowed:
        _fail(path, "contains unsupported fields")
    return dict(value)


def _text(value: Any, limit: int, path: str) -> None:
    if type(value) is not str or len(value) > limit:
        _fail(path, f"must be text of at most {limit} characters")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in value):
        _fail(path, "contains control characters")


def _safe_url(value: str, path: str) -> None:
    if not value:
        return  # Explicitly blank means no link, not a fallback CTA.
    decoded = value
    for _ in range(12):
        if (
            any(c.isspace() or c == "\\" or unicodedata.category(c).startswith("C") for c in decoded)
            or decoded.startswith("//")
            or re.search(r"%(?![0-9a-fA-F]{2})", decoded)
        ):
            _fail(path, "unsafe URL")
        try:
            parsed = urlsplit(decoded)
            if decoded.startswith("/"):
                valid = not parsed.scheme and not parsed.netloc
            else:
                valid = (
                    parsed.scheme in ("http", "https") and bool(parsed.hostname)
                    and parsed.username is None and parsed.password is None
                )
                if valid:
                    parsed.port  # Validate malformed ports as well.
            if not valid:
                _fail(path, "use an absolute local path or HTTP(S) URL without credentials")
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"PUBLIC_PAGES_CONFIG {path}: unsafe URL") from exc
        next_value = unquote(decoded, errors="strict")
        if next_value == decoded:
            return
        decoded = next_value
    _fail(path, "excessive URL encoding")


def _content_fields(obj: dict[str, Any], path: str) -> None:
    for key, value in obj.items():
        field = f"{path}.{key}"
        if key in _TEXT_LIMITS:
            _text(value, _TEXT_LIMITS[key], field)
            if key == "cta_url":
                _safe_url(value, field)
        elif key in ("enabled", "show_in_nav"):
            if type(value) is not bool:
                _fail(field, "must be a boolean")
        elif key == "order":
            if type(value) is not int or not -1000000 <= value <= 1000000:
                _fail(field, "must be a bounded integer, not a boolean")
        elif key in ("paragraphs", "checklist"):
            if type(value) is not list or len(value) > 50:
                _fail(field, "must be a list of at most 50 strings")
            for index, text in enumerate(value):
                _text(text, 5000, f"{field}[{index}]")
        elif key == "items":
            if type(value) is not list or len(value) > 50:
                _fail(field, "must be a list of at most 50 objects")
            for index, item in enumerate(value):
                item_path = f"{field}[{index}]"
                item = _object(item, _ITEM_FIELDS, item_path)
                for name, text in item.items():
                    _text(text, 2048 if name == "url" else 5000, f"{item_path}.{name}")
                    if name == "url":
                        _safe_url(text, f"{item_path}.url")


def _structured(value: Any, *, blocks: bool, path: str) -> list[dict[str, Any]]:
    limit = 30 if blocks else 50
    if type(value) is not list or len(value) > limit:
        _fail(path, f"must be an ordered list of at most {limit} entries")
    result = []
    for index, entry in enumerate(value):
        item_path = f"{path}[{index}]"
        if blocks and type(entry) is str:
            entry = {"type": entry}
        obj = _object(entry, _CONTENT | {"type", "enabled", "order"}, item_path)
        kind = obj.get("type")
        if type(kind) is not str:
            _fail(item_path, "requires a string type")
        kind = kind if blocks else _ALIASES.get(kind, kind)
        if kind not in (_BLOCKS if blocks else _SECTIONS):
            _fail(item_path, "unknown block/section type")
        obj["type"] = kind
        _content_fields(obj, item_path)
        obj.setdefault("enabled", True)
        result.append(obj)
    return result


def _page(value: Any, path: str, *, custom: bool = False) -> dict[str, Any]:
    obj = _object(value, _PAGE_FIELDS | ({"slug"} if custom else set()), path)
    _content_fields(obj, path)
    if "sections" in obj:
        obj["sections"] = _structured(obj["sections"], blocks=False, path=f"{path}.sections")
    if custom:
        _validate_slug(obj.get("slug"), path)
        if not obj.get("title", "").strip():
            _fail(path, "custom pages require a nonempty title")
        obj.setdefault("nav_label", obj["title"][:120])
        obj.setdefault("enabled", True)
        obj.setdefault("show_in_nav", False)
        obj.setdefault("order", 100)
        obj.setdefault("meta_description", "")
        obj.setdefault("sections", [])
    return obj


def _validate_slug(slug: Any, path: str = "slug") -> None:
    if type(slug) is not str or len(slug) > 80 or not _SLUG.fullmatch(slug) or slug in _RESERVED:
        _fail(path, "slug must be unreserved lowercase hyphenated text, at most 80 characters")


def _manifest(value: Any) -> dict[str, Any]:
    _json_tree(value)
    if type(value) is list:
        value = {"home_blocks": value}
    obj = _object(value, {"home_blocks", "pages", "custom_pages"}, "manifest")
    if "home_blocks" in obj:
        obj["home_blocks"] = _structured(obj["home_blocks"], blocks=True, path="home_blocks")
    if "pages" in obj:
        raw_pages = obj["pages"]
        if type(raw_pages) is list:
            pages = {}
            for index, entry in enumerate(raw_pages):
                entry = _object(entry, _PAGE_FIELDS | {"key"}, f"pages[{index}]")
                key = entry.pop("key", None)
                if type(key) is not str or key not in STANDARD_PAGES or key in pages:
                    _fail("pages", "unknown or duplicate page key")
                pages[key] = _page(entry, f"pages.{key}")
                pages[key].setdefault("order", index * 10)
            # Preserve list replacement semantics through the map-based merge.
            obj["pages"] = [{"key": key, **page} for key, page in pages.items()]
        elif type(raw_pages) is dict:
            if set(raw_pages) - set(STANDARD_PAGES):
                _fail("pages", "unknown standard page key")
            obj["pages"] = {key: _page(page, f"pages.{key}") for key, page in raw_pages.items()}
        else:
            _fail("pages", "must be a page map or ordered list")
    if "custom_pages" in obj:
        custom = obj["custom_pages"]
        if type(custom) is not list or len(custom) > 30:
            _fail("custom_pages", "must be a list of at most 30 pages")
        obj["custom_pages"] = [_page(page, f"custom_pages[{i}]", custom=True) for i, page in enumerate(custom)]
        slugs = [page["slug"] for page in obj["custom_pages"]]
        if len(set(slugs)) != len(slugs):
            _fail("custom_pages", "duplicate slug")
    return obj


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _copy(value: Any) -> Any:
    """Also thaw tenancy's mappingproxy/tuple snapshots for JSON validation."""
    nodes = 0

    def visit(item: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 4000:
            _fail("manifest", "exceeds depth or node limits")
        if isinstance(item, Mapping):
            if len(item) > 64:
                _fail("manifest", "too many object fields")
            return {key: visit(child, depth + 1) for key, child in item.items()}
        if type(item) in (list, tuple):
            if len(item) > 100:
                _fail("manifest", "too many list entries")
            return [visit(child, depth + 1) for child in item]
        return item

    return visit(value, 0)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = _copy(base)
    for key, value in override.items():
        result[key] = (
            _merge(result[key], value)
            if type(result.get(key)) is dict and type(value) is dict else _copy(value)
        )
    return result


@lru_cache(maxsize=1)
def _presets() -> Mapping[str, Any]:
    path = Path(__file__).resolve().parent.parent / "data" / "site_presets.json"

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in site presets")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as source:
        raw = json.load(source, object_pairs_hook=unique_object)
    if type(raw) is not dict or set(raw) != {
        DEFAULT_PRESET, "specialty_contractor", "minimal_quote_funnel",
    }:
        raise ValueError("Site presets must contain exactly the three builtin presets")
    return _freeze({name: _manifest(manifest) for name, manifest in raw.items()})


def preset_names() -> list[str]:
    return list(_presets())


def validate_public_settings(preset: str, manifest: Any) -> None:
    """Pure validation entry point: no Flask context, tenancy or database access.

    Pass {} for an absent override; explicit None is invalid. Inputs must be
    JSON-native, not template objects, callables, tuples or arbitrary mappings.
    """
    if type(preset) is not str or preset not in _presets():
        raise ValueError("Unknown public site preset")
    _manifest(manifest)


def _runtime_settings() -> dict[str, Any]:
    # Lazy import: config startup/operator validation must not import tenancy.
    from flask import current_app
    from app.tenancy import current_tenant_settings

    settings = dict(current_tenant_settings())
    # Existing tenancy only copies its allowlisted app defaults. New selectors
    # still work as app defaults without changing that module; tenant wins.
    for key in ("SITE_PRESET", "PUBLIC_PAGES_CONFIG"):
        if key not in settings and key in current_app.config:
            settings[key] = current_app.config[key]
    return settings


def _enabled(key: str, manifest: Mapping[str, Any], settings: Mapping[str, Any]) -> bool:
    page = manifest["pages"].get(key)
    return bool(page and page["enabled"] and (key not in _FLAGS or settings.get(_FLAGS[key], False)))


def _effective(settings: Mapping[str, Any]) -> dict[str, Any]:
    from flask import g, has_request_context
    cacheable = has_request_context() and hasattr(g, "_request_registry") and not hasattr(g, "_operator_registry")
    if cacheable and hasattr(g, "_public_pages_manifest"):
        return g._public_pages_manifest
    preset = settings.get("SITE_PRESET", DEFAULT_PRESET)
    raw = _copy(settings.get("PUBLIC_PAGES_CONFIG", {}))
    if type(preset) is not str or preset not in _presets():
        raise ValueError("Unknown public site preset")
    manifest = _merge(_copy(_presets()[preset]), _manifest(raw))
    pages = manifest.get("pages", {})
    replacing = type(pages) is list
    if replacing:
        pages = {page["key"]: {k: v for k, v in page.items() if k != "key"} for page in pages}
    result = {}
    for key in dict.fromkeys((*pages, *STANDARD_PAGES)):
        index = STANDARD_PAGES.index(key)
        title = _TITLES[index]
        defaults = {
            "enabled": key == "home" if replacing and key not in pages else True,
            "show_in_nav": key in ("home", "services", "gallery", "about", "contact"),
            "nav_label": title, "title": title, "meta_description": "",
            "hours": "", "coverage": "", "directions": "", "address": "",
            "order": index * 10, "sections": [],
        }
        result[key] = _merge(defaults, pages.get(key, {}))
    manifest["pages"] = result
    manifest.setdefault("home_blocks", [])
    manifest.setdefault("custom_pages", [])

    # Only generated defaults are retargeted. Explicit blank URLs stay blank.
    target = next((key for key in ("quote_request", "contact") if _enabled(key, manifest, settings)), None)
    default_url = {"quote_request": "/quote-request", "contact": "/contact"}.get(target, "")
    if target is not None:
        from flask import has_request_context, url_for
        if has_request_context():
            default_url = url_for(_ENDPOINTS[target])

    def defaults_for(entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            if entry["type"] in ("hero", "cta", "quote_cta") and "cta_url" not in entry:
                entry["cta_url"] = default_url
                entry.setdefault("cta_label", "Get a Quote" if target == "quote_request" else "Contact" if target else "")

    defaults_for(manifest["home_blocks"])
    for page in (*result.values(), *manifest["custom_pages"]):
        defaults_for(page["sections"])
    if cacheable:
        g._public_pages_manifest = manifest
    return manifest


def get_public_manifest() -> Mapping[str, Any]:
    return _freeze(_effective(_runtime_settings()))


def home_blocks() -> tuple[Mapping[str, Any], ...]:
    settings = _runtime_settings()
    manifest = _effective(settings)
    result = []
    for block in manifest["home_blocks"]:
        if not block["enabled"]:
            continue
        if block["type"] == "services_preview" and not _enabled("services", manifest, settings):
            continue
        if block["type"] == "gallery_preview":
            if not _enabled("gallery", manifest, settings):
                continue
            from app.services.gallery_catalog import has_public_gallery_items
            if not has_public_gallery_items():
                continue
        result.append(_freeze(block))
    return tuple(result)


def page_config(key: str) -> Mapping[str, Any]:
    if type(key) is not str or key not in STANDARD_PAGES:
        raise NotFound()
    return get_public_manifest()["pages"][key]


def page_enabled(key: str) -> bool:
    if type(key) is not str or key not in STANDARD_PAGES:
        return False
    settings = _runtime_settings()
    return _enabled(key, _effective(settings), settings)


def require_page(key: str) -> None:
    if not page_enabled(key):
        raise NotFound()


def custom_page(slug: str) -> Mapping[str, Any]:
    try:
        _validate_slug(slug)
    except ValueError as exc:
        raise NotFound() from exc
    for page in get_public_manifest()["custom_pages"]:
        if page["slug"] == slug and page["enabled"]:
            return page
    raise NotFound()


def navigation_links() -> list[dict[str, str]]:
    from flask import url_for

    settings = _runtime_settings()
    manifest = _effective(settings)
    candidates = []
    for key, page in manifest["pages"].items():
        if not page["show_in_nav"] or not _enabled(key, manifest, settings):
            continue
        if key == "gallery":
            from app.services.gallery_catalog import has_public_gallery_items
            if not has_public_gallery_items():
                continue
        candidates.append((page["order"], key, page, _ENDPOINTS[key], {}))
    for page in manifest["custom_pages"]:
        if page["enabled"] and page["show_in_nav"]:
            candidates.append((page["order"], page["slug"], page, "main.custom_page", {"slug": page["slug"]}))
    # Python's stable sort preserves standard and custom declaration order ties.
    candidates.sort(key=lambda candidate: candidate[0])
    return [
        {"key": key, "label": page["nav_label"], "url": url_for(endpoint, **values)}
        for _, key, page, endpoint, values in candidates
    ]