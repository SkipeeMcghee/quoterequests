from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, UnidentifiedImageError
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from app.models import CustomerPhoto, RequestPhoto
from app.services.media import resolve_upload_path


IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}


def save_request_photos(files: list[FileStorage], quote_request_id: int) -> list[RequestPhoto]:
    photos: list[RequestPhoto] = []
    try:
        for file in files:
            if file is None or not file.filename:
                continue
            extension = _validate_file(file)
            original_name = secure_filename(file.filename)
            if not original_name:
                raise BadRequest("Uploaded file name is invalid.")
            relative_dir, target_dir = get_request_photo_dirs(quote_request_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(original_name).stem or "photo"
            stored_name = f"{uuid4().hex}-{stem}.{extension}"
            _save_file(file, str(relative_dir / stored_name))
            photos.append(RequestPhoto(file_path=str(relative_dir / stored_name).replace("\\", "/")))
    except Exception:
        for photo in photos:
            delete_upload_file(photo.file_path, categories=("quote_requests",))
        raise
    return photos


def _validate_file(file: FileStorage) -> str:
    if "." not in file.filename:
        raise BadRequest("Uploaded files must include an extension.")

    extension = file.filename.rsplit(".", 1)[1].lower()
    allowed_extensions = current_app.config["ALLOWED_IMAGE_EXTENSIONS"]
    if extension not in allowed_extensions:
        raise BadRequest("Only image uploads are allowed.")
    if file.mimetype and not file.mimetype.startswith("image/"):
        raise BadRequest("Uploaded file must be an image.")
    if not _matches_signature(file, extension):
        current_app.logger.warning(
            "Rejected image upload with invalid signature: %s mimetype=%s",
            file.filename,
            file.mimetype,
        )
        raise BadRequest(
            f"Uploaded file '{secure_filename(file.filename)}' content does not match a supported image type."
        )
    return extension


def get_request_photo_dirs(quote_request_id: int) -> tuple[Path, Path]:
    relative_dir = Path("uploads") / "quote_requests" / str(quote_request_id)
    target_dir = _require_upload_path(str(relative_dir))
    return relative_dir, target_dir


def cleanup_request_photo_dir(quote_request_id: int) -> None:
    _, target_dir = get_request_photo_dirs(quote_request_id)
    _cleanup_photo_dir(target_dir)


def save_customer_photos(files: list[FileStorage], customer_id: int) -> list[CustomerPhoto]:
    photos: list[CustomerPhoto] = []
    try:
        for file in files:
            if file is None or not file.filename:
                continue
            extension = _validate_file(file)
            original_name = secure_filename(file.filename)
            if not original_name:
                raise BadRequest("Uploaded file name is invalid.")
            relative_dir, target_dir = get_customer_photo_dirs(customer_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(original_name).stem or "photo"
            stored_name = f"{uuid4().hex}-{stem}.{extension}"
            _save_file(file, str(relative_dir / stored_name))
            photos.append(CustomerPhoto(file_path=str(relative_dir / stored_name).replace("\\", "/")))
    except Exception:
        for photo in photos:
            delete_upload_file(photo.file_path, categories=("customers",))
        raise
    return photos


def save_gallery_image(file: FileStorage) -> str:
    if file is None or not file.filename:
        raise BadRequest("Choose an image to upload.")

    extension = _validate_file(file)
    original_name = secure_filename(file.filename)
    if not original_name:
        raise BadRequest("Uploaded file name is invalid.")

    relative_dir, target_dir = get_gallery_image_dirs()
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(original_name).stem or "gallery-image"
    stored_name = f"{uuid4().hex}-{stem}.{extension}"
    _save_file(file, str(relative_dir / stored_name))
    return str(relative_dir / stored_name).replace("\\", "/")


def get_customer_photo_dirs(customer_id: int) -> tuple[Path, Path]:
    relative_dir = Path("uploads") / "customers" / str(customer_id)
    target_dir = _require_upload_path(str(relative_dir))
    return relative_dir, target_dir


def get_gallery_image_dirs() -> tuple[Path, Path]:
    relative_dir = Path("uploads") / "gallery"
    target_dir = _require_upload_path(str(relative_dir))
    return relative_dir, target_dir


def cleanup_customer_photo_dir(customer_id: int) -> None:
    _, target_dir = get_customer_photo_dirs(customer_id)
    _cleanup_photo_dir(target_dir)


def _cleanup_photo_dir(target_dir: Path) -> None:
    if target_dir.exists():
        try:
            shutil.rmtree(target_dir)
        except OSError:
            current_app.logger.exception("Unable to remove tenant photo directory at %s", target_dir)


def _require_upload_path(relative_path: str) -> Path:
    target = resolve_upload_path(relative_path)
    if target is None:
        raise BadRequest("Invalid upload storage path.")
    return target


def _save_file(file: FileStorage, relative_path: str) -> None:
    target = _require_upload_path(relative_path)
    try:
        file.save(target)
    except Exception:
        delete_upload_file(relative_path)
        raise


def delete_upload_file(relative_path: str, *, categories: tuple[str, ...] = ("quote_requests", "customers", "gallery")) -> None:
    target = resolve_upload_path(relative_path, categories=categories)
    if target is None:
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("Unable to remove tenant upload at %s", target)


def delete_gallery_image(image_path: str | None) -> None:
    if not image_path:
        return

    delete_upload_file(image_path, categories=("gallery",))


def _matches_signature(file: FileStorage, extension: str) -> bool:
    stream = file.stream
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass

    format_name = None
    try:
        with Image.open(stream) as image:
            image.verify()
            format_name = image.format.lower() if image.format else None
    except (UnidentifiedImageError, OSError, ValueError):
        format_name = None
    finally:
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass

    if format_name:
        if format_name == extension:
            return True
        if format_name == "jpeg" and extension in {"jpg", "jpeg"}:
            return True

    header = stream.read(256)
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass

    if extension == "webp":
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return True
    elif extension in {"jpg", "jpeg"}:
        if header.startswith(b"\xff\xd8"):
            return True
    else:
        if any(header.startswith(signature) for signature in IMAGE_SIGNATURES[extension]):
            return True

    current_app.logger.warning(
        "Rejected image upload: %s extension=%s detected=%s header=%s",
        file.filename,
        extension,
        format_name,
        header[:16],
    )
    return False