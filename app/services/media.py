"""Access rules for uploaded files.

Explicit tenants store uploads outside the shared static tree. Private categories
require authentication; gallery images use a tenant-aware public endpoint. The
automatic local/test tenant retains its legacy public static gallery URLs.
"""

from __future__ import annotations

from pathlib import Path

from flask import current_app, url_for

from app.tenancy import is_default_tenant, tenant_upload_root

# First path segment under uploads/ that must never be served by the static route.
PRIVATE_UPLOAD_ROOTS = ("quote_requests", "customers")


def normalize_relative_path(relative_path: str) -> str:
    return (relative_path or "").replace("\\", "/").lstrip("/")


def upload_category(relative_path: str) -> str:
    """Category without the leading `uploads/` segment, e.g. `customers`."""

    parts = [part for part in normalize_relative_path(relative_path).split("/") if part]
    if parts and parts[0] == "uploads":
        parts = parts[1:]
    return parts[0] if parts else ""


def is_private_upload(relative_path: str) -> bool:
    return upload_category(relative_path) in PRIVATE_UPLOAD_ROOTS


def storage_key(relative_path: str) -> str:
    """Path relative to the uploads root, for use in the media route."""

    parts = [part for part in normalize_relative_path(relative_path).split("/") if part]
    if parts and parts[0] == "uploads":
        parts = parts[1:]
    return "/".join(parts)


def media_url(relative_path: str) -> str:
    """Public URL for a stored upload, routed according to its privacy."""

    normalized = normalize_relative_path(relative_path)
    if not normalized:
        return ""

    if is_private_upload(normalized):
        return url_for("admin.uploaded_media", storage_path=storage_key(normalized))

    if upload_category(normalized) == "gallery" and not is_default_tenant():
        return url_for("main.public_media", storage_path=storage_key(normalized))

    return url_for("static", filename=normalized)


def resolve_upload_path(
    relative_path: str,
    *,
    categories: tuple[str, ...] = (*PRIVATE_UPLOAD_ROOTS, "gallery"),
) -> Path | None:
    """Resolve a logical upload key beneath the active tenant's storage root."""

    if not relative_path or relative_path.startswith(("/", "\\")):
        current_app.logger.warning("Rejected an empty or absolute upload key.")
        return None
    parts = relative_path.replace("\\", "/").split("/")
    if parts[0] == "uploads":
        parts = parts[1:]
    if (
        not parts or parts[0] not in categories
        or any(part in ("", ".", "..") or ":" in part for part in parts)
        or any(ord(char) < 32 for char in relative_path)
    ):
        current_app.logger.warning("Rejected an invalid upload key or category.")
        return None

    root = tenant_upload_root()
    candidate = root.joinpath(*parts).resolve()

    try:
        resolved_parts = candidate.relative_to(root).parts
    except ValueError:
        current_app.logger.warning("Rejected an upload path outside the tenant storage root.")
        return None
    if not resolved_parts or resolved_parts[0] not in categories:
        current_app.logger.warning("Rejected an upload path outside its allowed category.")
        return None
    return candidate


def resolve_private_file(storage_path: str) -> Path | None:
    candidate = resolve_upload_path(storage_path, categories=PRIVATE_UPLOAD_ROOTS)
    return candidate if candidate is not None and candidate.is_file() else None


def resolve_public_file(storage_path: str) -> Path | None:
    candidate = resolve_upload_path(storage_path, categories=("gallery",))
    return candidate if candidate is not None and candidate.is_file() else None
