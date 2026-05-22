from __future__ import annotations

from io import BytesIO

from app.extensions import db
from app.models import GalleryItem, ServiceOption


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _login_as_admin(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def test_gallery_surfaces_stay_hidden_when_disabled(client, app, admin_user):
    app.config["ENABLE_GALLERY"] = False

    with app.app_context():
        service = ServiceOption.query.filter_by(name="Painting").one()
        db.session.add(
            GalleryItem(
                image_path="uploads/gallery/front-entry.png",
                title="Front entry refresh",
                caption="Trim touch-ups and a cleaner first impression.",
                service=service,
                featured=True,
                is_active=True,
                display_order=0,
            )
        )
        db.session.commit()

    home_response = client.get("/")
    assert home_response.status_code == 200
    assert 'href="/gallery"' not in home_response.get_data(as_text=True)

    gallery_response = client.get("/gallery")
    assert gallery_response.status_code == 404

    _login_as_admin(client, admin_user)
    admin_gallery_response = client.get("/admin/content/gallery")
    assert admin_gallery_response.status_code == 404


def test_gallery_page_renders_when_enabled_with_active_items(app):
    app.config["ENABLE_GALLERY"] = True

    with app.app_context():
        service = ServiceOption.query.filter_by(name="Painting").one()
        db.session.add_all(
            [
                GalleryItem(
                    image_path="uploads/gallery/front-entry.png",
                    title="Front entry refresh",
                    caption="Trim touch-ups and a cleaner first impression.",
                    service=service,
                    featured=True,
                    is_active=True,
                    display_order=0,
                ),
                GalleryItem(
                    image_path="uploads/gallery/exterior-detail.png",
                    title="Exterior detail work",
                    caption="Finish work photographed after final cleanup.",
                    featured=False,
                    is_active=True,
                    display_order=1,
                ),
            ]
        )
        db.session.commit()

    client = app.test_client()
    response = client.get("/gallery")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Project gallery" in body
    assert "Front entry refresh" in body
    assert "Trim touch-ups and a cleaner first impression." in body
    assert "Painting" in body
    assert "/static/uploads/gallery/front-entry.png" in body

    home_response = client.get("/")
    assert home_response.status_code == 200
    assert 'href="/gallery"' in home_response.get_data(as_text=True)


def test_gallery_page_404s_without_active_items_even_when_enabled(app):
    app.config["ENABLE_GALLERY"] = True
    client = app.test_client()

    home_response = client.get("/")
    assert home_response.status_code == 200
    assert 'href="/gallery"' not in home_response.get_data(as_text=True)

    gallery_response = client.get("/gallery")
    assert gallery_response.status_code == 404


def test_admin_content_page_lists_enabled_modules(client, app, admin_user):
    app.config.update(ENABLE_GALLERY=True, ENABLE_SERVICES=True)
    _login_as_admin(client, admin_user)

    response = client.get("/admin/content")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Gallery" in body
    assert "Services" in body
    assert 'href="/admin/content/gallery"' in body
    assert 'href="/admin/settings/services"' in body


def test_admin_can_upload_update_reorder_archive_and_reactivate_gallery_items(client, app, admin_user):
    app.config["ENABLE_GALLERY"] = True
    with app.app_context():
        service = ServiceOption.query.filter_by(name="Painting").one()
        service_id = service.id

    _login_as_admin(client, admin_user)

    create_response = client.post(
        "/admin/content/gallery",
        data={
            "gallery-create-image": (BytesIO(PNG_BYTES), "front-entry.png"),
            "gallery-create-title": "Front entry refresh",
            "gallery-create-caption": "Trim touch-ups and a cleaner first impression.",
            "gallery-create-service_id": str(service_id),
            "gallery-create-featured": "y",
            "gallery-create-display_order": "1",
            "gallery-create-submit": "Upload Image",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    second_response = client.post(
        "/admin/content/gallery",
        data={
            "gallery-create-image": (BytesIO(PNG_BYTES), "exterior-detail.png"),
            "gallery-create-title": "Exterior detail work",
            "gallery-create-caption": "Finish work photographed after final cleanup.",
            "gallery-create-service_id": "0",
            "gallery-create-display_order": "0",
            "gallery-create-submit": "Upload Image",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert second_response.status_code == 302

    with app.app_context():
        first_item = GalleryItem.query.filter_by(title="Front entry refresh").one()
        second_item = GalleryItem.query.filter_by(title="Exterior detail work").one()
        assert first_item.service_id == service_id
        assert first_item.featured is True
        assert first_item.is_active is True
        assert first_item.image_path.startswith("uploads/gallery/")
        first_item_id = first_item.id
        second_item_id = second_item.id

    update_response = client.post(
        f"/admin/content/gallery/{first_item_id}",
        data={
            f"gallery-{first_item_id}-title": "Front entry repaint",
            f"gallery-{first_item_id}-caption": "Fresh paint with cleaner trim lines.",
            f"gallery-{first_item_id}-service_id": "0",
            f"gallery-{first_item_id}-display_order": "2",
            f"gallery-{first_item_id}-submit": "Save Changes",
        },
        follow_redirects=False,
    )
    assert update_response.status_code == 302

    with app.app_context():
        first_item = db.session.get(GalleryItem, first_item_id)
        assert first_item is not None
        assert first_item.title == "Front entry repaint"
        assert first_item.caption == "Fresh paint with cleaner trim lines."
        assert first_item.service_id is None
        assert first_item.featured is False
        assert first_item.display_order == 2

    public_response = client.get("/gallery")
    assert public_response.status_code == 200
    public_body = public_response.get_data(as_text=True)
    assert public_body.index("Exterior detail work") < public_body.index("Front entry repaint")

    archive_response = client.post(
        f"/admin/content/gallery/{first_item_id}/status",
        data={},
        follow_redirects=False,
    )
    assert archive_response.status_code == 302

    with app.app_context():
        first_item = db.session.get(GalleryItem, first_item_id)
        assert first_item is not None
        assert first_item.is_active is False

    detail_response = client.get("/gallery")
    assert detail_response.status_code == 200
    assert "Front entry repaint" not in detail_response.get_data(as_text=True)

    second_archive_response = client.post(
        f"/admin/content/gallery/{second_item_id}/status",
        data={},
        follow_redirects=False,
    )
    assert second_archive_response.status_code == 302
    assert client.get("/gallery").status_code == 404

    reactivate_response = client.post(
        f"/admin/content/gallery/{first_item_id}/status",
        data={},
        follow_redirects=False,
    )
    assert reactivate_response.status_code == 302

    with app.app_context():
        first_item = db.session.get(GalleryItem, first_item_id)
        assert first_item is not None
        assert first_item.is_active is True

    restored_response = client.get("/gallery")
    assert restored_response.status_code == 200
    assert "Front entry repaint" in restored_response.get_data(as_text=True)