from __future__ import annotations

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest, NotFound

from app.extensions import db
from app.models import GalleryItem
from app.models import ServiceOption
from app.services.uploads import delete_gallery_image, save_gallery_image


def is_gallery_enabled(config=None) -> bool:
    settings = config or current_app.config
    return bool(settings.get("ENABLE_GALLERY", False))


def require_gallery_enabled() -> None:
    if not is_gallery_enabled():
        raise NotFound()


def list_gallery_items(*, include_inactive: bool = True) -> list[GalleryItem]:
    require_gallery_enabled()
    return list(GalleryItem.ordered_query(include_inactive=include_inactive).all())


def list_public_gallery_items() -> list[GalleryItem]:
    if not is_gallery_enabled():
        return []
    return list(GalleryItem.ordered_query(include_inactive=False).all())


def has_public_gallery_items() -> bool:
    if not is_gallery_enabled():
        return False
    return GalleryItem.query.filter(GalleryItem.is_active.is_(True)).first() is not None


def get_gallery_item(item_id: int) -> GalleryItem:
    require_gallery_enabled()
    gallery_item = db.session.get(GalleryItem, item_id)
    if gallery_item is None:
        raise NotFound("Gallery image not found.")
    return gallery_item


def create_gallery_item(
    *,
    image_file: FileStorage,
    title: str,
    caption: str | None = None,
    service_id: int | None = None,
    featured: bool = False,
    display_order: int | None = None,
) -> GalleryItem:
    require_gallery_enabled()
    image_path = save_gallery_image(image_file)
    try:
        gallery_item = GalleryItem(
            image_path=image_path,
            title=_clean_title(title),
            caption=_clean_caption(caption),
            service=_resolve_service(service_id),
            featured=bool(featured),
            is_active=True,
            display_order=_next_display_order() if display_order is None else _clean_display_order(display_order),
        )
        db.session.add(gallery_item)
        db.session.commit()
    except Exception:
        delete_gallery_image(image_path)
        raise
    return gallery_item


def update_gallery_item(
    item_id: int,
    *,
    title: str,
    caption: str | None = None,
    service_id: int | None = None,
    featured: bool = False,
    display_order: int | None = None,
) -> GalleryItem:
    require_gallery_enabled()
    gallery_item = get_gallery_item(item_id)
    gallery_item.title = _clean_title(title)
    gallery_item.caption = _clean_caption(caption)
    gallery_item.service = _resolve_service(service_id)
    gallery_item.featured = bool(featured)
    if display_order is not None:
        gallery_item.display_order = _clean_display_order(display_order)
    db.session.commit()
    return gallery_item


def reorder_gallery_items(*, item_ids: list[int], visible_item_ids: set[int]) -> list[GalleryItem]:
    require_gallery_enabled()
    if not item_ids:
        raise BadRequest("Choose at least one gallery image to arrange.")

    normalized_item_ids: list[int] = []
    seen_item_ids: set[int] = set()
    for raw_item_id in item_ids:
        item_id = int(raw_item_id)
        if item_id in seen_item_ids:
            raise BadRequest("Gallery arrangement contains duplicate images.")
        seen_item_ids.add(item_id)
        normalized_item_ids.append(item_id)

    normalized_visible_ids = {int(item_id) for item_id in visible_item_ids}
    if not normalized_visible_ids.issubset(seen_item_ids):
        raise BadRequest("Gallery arrangement included an unknown visibility selection.")

    gallery_items = {
        gallery_item.id: gallery_item
        for gallery_item in GalleryItem.query.filter(GalleryItem.id.in_(normalized_item_ids)).all()
    }
    if len(gallery_items) != len(normalized_item_ids):
        raise BadRequest("One or more gallery images could not be found.")

    for index, item_id in enumerate(normalized_item_ids):
        gallery_item = gallery_items[item_id]
        gallery_item.display_order = index
        gallery_item.is_active = item_id in normalized_visible_ids

    db.session.commit()
    return [gallery_items[item_id] for item_id in normalized_item_ids]


def set_gallery_item_active(item_id: int, *, is_active: bool) -> GalleryItem:
    require_gallery_enabled()
    gallery_item = get_gallery_item(item_id)
    gallery_item.is_active = bool(is_active)
    db.session.commit()
    return gallery_item


def _resolve_service(service_id: int | None) -> ServiceOption | None:
    if service_id in (None, 0):
        return None

    service = db.session.get(ServiceOption, int(service_id))
    if service is None:
        raise BadRequest("Choose a valid service.")
    return service


def _clean_title(raw_title: str | None) -> str:
    cleaned_title = (raw_title or "").strip()
    if not cleaned_title:
        raise BadRequest("Gallery title is required.")
    if len(cleaned_title) > 80:
        raise BadRequest("Gallery title must be 80 characters or fewer.")
    return cleaned_title


def _clean_caption(raw_caption: str | None) -> str | None:
    cleaned_caption = (raw_caption or "").strip()
    if len(cleaned_caption) > 180:
        raise BadRequest("Gallery caption must be 180 characters or fewer.")
    return cleaned_caption or None


def _clean_display_order(raw_display_order: int | None) -> int:
    if raw_display_order is None:
        raise BadRequest("Display order is required.")
    if int(raw_display_order) < 0:
        raise BadRequest("Display order must be zero or greater.")
    return int(raw_display_order)


def _next_display_order() -> int:
    max_display_order = db.session.query(db.func.max(GalleryItem.display_order)).scalar()
    if max_display_order is None:
        return 0
    return int(max_display_order) + 1