from __future__ import annotations

from pathlib import Path

import pytest

from app.extensions import db
from app.models import Customer, CustomerPhoto, QuoteRequest, RequestPhoto, User
from app.services import media as media_service


@pytest.fixture()
def upload_root(app, tmp_path):
    """Private files go in the configured upload folder, which tests can own."""

    root = tmp_path / "uploads"
    (root / "customers" / "1").mkdir(parents=True)
    (root / "quote_requests" / "1").mkdir(parents=True)
    (root / "customers" / "1" / "photo.jpg").write_bytes(b"customer-private")
    (root / "quote_requests" / "1" / "photo.jpg").write_bytes(b"request-private")
    app.config["UPLOAD_FOLDER"] = str(root)
    return root


@pytest.fixture()
def public_gallery_file(app):
    """Gallery images genuinely live in the static tree and stay public."""

    folder = Path(app.static_folder) / "uploads" / "gallery"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "_media_test_public.jpg"
    path.write_bytes(b"public-gallery")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def login(client, app, admin_user):
    """Sign in without repeating a password literal in every test."""

    with app.app_context():
        user_id = User.query.filter_by(email=admin_user).first().id
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_categories_are_classified_by_privacy():
    assert media_service.is_private_upload("uploads/customers/1/photo.jpg") is True
    assert media_service.is_private_upload("uploads/quote_requests/1/photo.jpg") is True
    assert media_service.is_private_upload("uploads/gallery/public.jpg") is False
    assert media_service.is_private_upload("assets/images/Logowhite.png") is False


def test_media_url_routes_private_files_through_the_admin_route(app):
    with app.test_request_context("/"):
        private = media_service.media_url("uploads/customers/1/photo.jpg")
        public = media_service.media_url("uploads/gallery/public.jpg")

    assert private.startswith("/admin/media/")
    assert public.startswith("/static/uploads/gallery/")


def test_static_route_no_longer_serves_request_photos(client, upload_root):
    assert client.get("/static/uploads/quote_requests/1/photo.jpg").status_code == 404


def test_static_route_no_longer_serves_customer_photos(client, upload_root):
    assert client.get("/static/uploads/customers/1/photo.jpg").status_code == 404


def test_gallery_images_stay_public(client, public_gallery_file):
    response = client.get("/static/uploads/gallery/_media_test_public.jpg")

    assert response.status_code == 200
    assert response.data == b"public-gallery"


def test_anonymous_user_is_sent_to_login_not_the_file(client, upload_root):
    response = client.get("/admin/media/quote_requests/1/photo.jpg")

    assert response.status_code in (302, 401)
    if response.status_code == 302:
        assert "/admin" in response.headers["Location"]


def test_signed_in_user_gets_the_file(client, app, admin_user, upload_root):
    login(client, app, admin_user)

    response = client.get("/admin/media/quote_requests/1/photo.jpg")

    assert response.status_code == 200
    assert response.data == b"request-private"
    assert "noindex" in response.headers.get("X-Robots-Tag", "")
    assert "private" in response.headers.get("Cache-Control", "")


def test_gallery_path_is_not_reachable_through_the_media_route(client, app, admin_user, upload_root):
    login(client, app, admin_user)

    assert client.get("/admin/media/gallery/public.jpg").status_code == 404


def test_traversal_out_of_the_upload_root_is_refused(client, app, admin_user, upload_root):
    login(client, app, admin_user)

    for attempt in (
        "/admin/media/customers/../../../etc/passwd",
        "/admin/media/customers/1/../../../../app.py",
        "/admin/media/quote_requests/..%2f..%2fconfig.py",
    ):
        assert client.get(attempt).status_code == 404


def test_missing_file_is_a_404(client, app, admin_user, upload_root):
    login(client, app, admin_user)

    assert client.get("/admin/media/customers/1/nope.jpg").status_code == 404


def test_request_detail_page_uses_the_media_route(app, client, admin_user, upload_root):
    app.config.update(ENABLE_SCHEDULING=True, ENABLE_CUSTOMER_RECORDS=True)
    with app.app_context():
        quote_request = QuoteRequest(
            request_number=0, full_name="Photo Owner", city="Daytona Beach", email="p@example.test"
        )
        db.session.add(quote_request)
        db.session.commit()
        db.session.add(
            RequestPhoto(
                quote_request_id=quote_request.id,
                file_path=f"uploads/quote_requests/{quote_request.id}/photo.jpg",
            )
        )
        db.session.commit()
        request_id = quote_request.id

    login(client, app, admin_user)
    body = client.get(f"/admin/requests/{request_id}").get_data(as_text=True)

    assert f"/admin/media/quote_requests/{request_id}/photo.jpg" in body
    assert f"/static/uploads/quote_requests/{request_id}" not in body


def test_customer_detail_page_uses_the_media_route(app, client, admin_user, upload_root):
    app.config.update(ENABLE_CUSTOMER_RECORDS=True)
    with app.app_context():
        customer = Customer(primary_name="Photo Customer", primary_city="Daytona Beach")
        db.session.add(customer)
        db.session.commit()
        db.session.add(
            CustomerPhoto(
                customer_id=customer.id,
                file_path=f"uploads/customers/{customer.id}/photo.jpg",
            )
        )
        db.session.commit()
        customer_id = customer.id

    login(client, app, admin_user)
    body = client.get(f"/admin/customers/{customer_id}").get_data(as_text=True)

    assert f"/admin/media/customers/{customer_id}/photo.jpg" in body
    assert f"/static/uploads/customers/{customer_id}" not in body
