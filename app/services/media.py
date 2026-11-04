"""Access rules for uploaded files.

Uploads live under `app/static/uploads`, which means Flask's static route would serve
them to anyone who guesses a URL. Gallery images are meant to be public; request and
customer photos are not - they are somebody's home, often with a gate code in the
filename metadata.

So: private categories are blocked on the static route and served through an
authenticated admin route instead. `media_url()` is the single place that decides which
is which, so templates never build these URLs by hand.
"""

from __future__ import annotations

from pathlib import Path

from flask import url_for

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

    return url_for("static", filename=normalized)


def resolve_private_file(upload_folder: str, storage_path: str) -> Path | None:
    """Absolute path for a private upload, or None if it escapes the uploads root."""

    key = storage_key(storage_path)
    if not key or upload_category(key) not in PRIVATE_UPLOAD_ROOTS:
        return None

    root = Path(upload_folder).resolve()
    candidate = (root / key).resolve()

    try:
        candidate.relative_to(root)
    except ValueError:
        return None

    if not candidate.is_file():
        return None

    return candidate
