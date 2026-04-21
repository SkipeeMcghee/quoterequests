from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest
from werkzeug.utils import secure_filename

from app.models import RequestPhoto


def save_request_photos(files: list[FileStorage], quote_request_id: int) -> list[RequestPhoto]:
    photos: list[RequestPhoto] = []
    for file in files:
        if file is None or not file.filename:
            continue

        extension = _validate_file(file)
        original_name = secure_filename(file.filename)
        relative_dir = Path("uploads") / "quote_requests" / str(quote_request_id)
        target_dir = Path(current_app.config["UPLOAD_FOLDER"]) / "quote_requests" / str(quote_request_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        stored_name = f"{uuid4().hex}-{original_name.rsplit('.', 1)[0]}.{extension}"
        absolute_path = target_dir / stored_name
        file.save(absolute_path)

        photos.append(RequestPhoto(file_path=str(relative_dir / stored_name).replace("\\", "/")))

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
    return extension