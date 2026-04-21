from __future__ import annotations

from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import QuoteRequest
from app.models.user import User


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_quote_request_page_renders(client):
    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Request a quote without the CRM overhead." in body
    assert "Full name" in body
    assert "Project description" in body


def test_quote_request_validation_errors_do_not_save_request(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "",
            "phone": "",
            "email": "not-an-email",
            "service_type": "",
            "address": "",
            "description": "",
            "preferred_contact_method": "",
            "preferred_contact_time": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "This field is required." in body
    assert "Invalid email address." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_public_quote_request_submission_creates_request(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Jordan Harper",
            "phone": "555-111-2222",
            "email": "jordan@example.com",
            "service_type": "Landscape Design",
            "address": "123 Garden St",
            "description": "Looking for a full backyard redesign.",
            "preferred_contact_method": "Email",
            "preferred_contact_time": "Afternoons",
            "photos": [(BytesIO(JPEG_BYTES), "yard.jpg")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.full_name == "Jordan Harper"
        assert quote_request.status == "New"
        assert len(quote_request.photos) == 1


def test_image_upload_is_stored_and_path_is_saved(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Morgan Ellis",
            "phone": "555-888-1111",
            "email": "morgan@example.com",
            "service_type": "Roof Repair",
            "address": "45 Cedar Ave",
            "description": "Leak around a skylight after heavy rain.",
            "preferred_contact_method": "Phone",
            "preferred_contact_time": "Evenings",
            "photos": [(BytesIO(JPEG_BYTES), "leak.jpg")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert len(quote_request.photos) == 1
        photo = quote_request.photos[0]
        assert photo.file_path.startswith("uploads/quote_requests/1/")
        stored_file = Path(app.config["UPLOAD_FOLDER"]) / Path(photo.file_path).relative_to("uploads")
        assert stored_file.exists()


def test_invalid_upload_type_is_rejected(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Taylor Reed",
            "phone": "555-000-1212",
            "email": "taylor@example.com",
            "service_type": "Window Cleaning",
            "address": "88 Pine St",
            "description": "Need exterior windows cleaned this month.",
            "preferred_contact_method": "Email",
            "preferred_contact_time": "Weekdays",
            "photos": [(BytesIO(b"not-an-image"), "notes.pdf")],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Images only." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_invalid_upload_content_is_rejected(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Signature Check",
            "phone": "555-121-1212",
            "email": "signature@example.com",
            "service_type": "Inspection",
            "address": "17 Walnut Ave",
            "description": "Testing image signature validation.",
            "preferred_contact_method": "Email",
            "preferred_contact_time": "Anytime",
            "photos": [(BytesIO(b"not-a-real-jpeg"), "fake.jpg")],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Uploaded file content does not match a supported image type." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_quote_request_persists_even_if_email_hook_fails(client, app, monkeypatch):
    import app.services.quotes as quote_service

    def raising_hook(_quote_request):
        raise RuntimeError("mail provider unavailable")

    monkeypatch.setattr(quote_service, "send_customer_confirmation", raising_hook)

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Email Hook Failure",
            "phone": "555-434-3434",
            "email": "hookfail@example.com",
            "service_type": "Painting",
            "address": "55 Cedar Way",
            "description": "Submission should still persist.",
            "preferred_contact_method": "Phone",
            "preferred_contact_time": "Morning",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        assert QuoteRequest.query.count() == 1


def test_thank_you_page_renders(client):
    response = client.get("/thank-you")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Thank you for reaching out." in body
    assert "Submit another request" in body


def test_uploaded_files_appear_on_admin_request_detail_page(client, app, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Avery Stone",
            "phone": "555-343-2222",
            "email": "avery@example.com",
            "service_type": "Deck Staining",
            "address": "18 Oak Lane",
            "description": "Deck needs sanding and staining before summer.",
            "preferred_contact_method": "Text",
            "preferred_contact_time": "Late afternoon",
            "photos": [(BytesIO(PNG_BYTES), "deck.png")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/requests/1")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Uploaded photos" in body
    assert "/static/uploads/quote_requests/1/" in body
    assert "Quote request photo 1" in body


def test_dashboard_lists_quote_requests(client, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Jamie Cole",
            "phone": "555-111-0000",
            "email": "jamie@example.com",
            "service_type": "Flooring",
            "address": "14 Birch Rd",
            "description": "Need new flooring in two bedrooms.",
            "preferred_contact_method": "Email",
            "preferred_contact_time": "Afternoons",
        },
        follow_redirects=False,
    )

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Quote requests" in body
    assert "Jamie Cole" in body
    assert "Flooring" in body


def test_dashboard_shows_newest_requests_first(client, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "First Request",
            "phone": "555-100-0001",
            "email": "first@example.com",
            "service_type": "Siding",
            "address": "1 First St",
            "description": "First request in the queue.",
            "preferred_contact_method": "Phone",
            "preferred_contact_time": "Morning",
        },
        follow_redirects=False,
    )
    client.post(
        "/quote-request",
        data={
            "full_name": "Second Request",
            "phone": "555-100-0002",
            "email": "second@example.com",
            "service_type": "Fence Repair",
            "address": "2 Second St",
            "description": "Second request in the queue.",
            "preferred_contact_method": "Email",
            "preferred_contact_time": "Evening",
        },
        follow_redirects=False,
    )

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.index("Second Request") < body.index("First Request")


def test_login_page_renders(client):
    response = client.get("/auth/login")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Admin login" in body
    assert "Password" in body


def test_password_hashing_works(app):
    with app.app_context():
        user = User(email="hashcheck@example.com")
        user.set_password("SecretPass123!")
        db.session.add(user)
        db.session.commit()

        assert user.password_hash != "SecretPass123!"
        assert user.check_password("SecretPass123!") is True
        assert user.check_password("wrong-password") is False


def test_protected_admin_routes_require_login(client):
    response = client.get("/admin/", follow_redirects=False)

    assert response.status_code == 302
    assert "/auth/login?next=%2Fadmin%2F" in response.headers["Location"]


def test_login_redirects_to_requested_admin_page(client, admin_user):
    login_page = client.get("/auth/login?next=/admin/")
    assert login_page.status_code == 200

    response = client.post(
        "/auth/login?next=/admin/",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/")


def test_logout_works_and_admin_routes_are_protected_after_logout(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    logout_response = client.post("/auth/logout", follow_redirects=False)
    protected_response = client.get("/admin/", follow_redirects=False)

    assert logout_response.status_code == 302
    assert logout_response.headers["Location"].endswith("/auth/login")
    assert protected_response.status_code == 302
    assert "/auth/login?next=%2Fadmin%2F" in protected_response.headers["Location"]


def test_create_dev_admin_command_creates_first_admin(app):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["create-dev-admin", "--email", "devadmin@example.com", "--password", "LocalPass123!"])

    assert result.exit_code == 0
    assert "Development admin user created." in result.output

    with app.app_context():
        user = User.query.filter_by(email="devadmin@example.com").first()
        assert user is not None
        assert user.check_password("LocalPass123!") is True


def test_admin_can_login_update_status_and_add_note(client, app, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "email": "casey@example.com",
            "service_type": "Painting",
            "address": "77 Market St",
            "description": "Interior repaint for living room and kitchen.",
            "preferred_contact_method": "Phone",
            "preferred_contact_time": "Mornings",
        },
        follow_redirects=False,
    )

    login_response = client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    assert login_response.status_code == 302
    assert login_response.headers["Location"].endswith("/admin/")

    status_response = client.post(
        "/admin/requests/1/status",
        data={"status": "Quoted"},
        follow_redirects=False,
    )
    note_response = client.post(
        "/admin/requests/1/notes",
        data={"note_text": "Reviewed photos and prepared pricing draft."},
        follow_redirects=False,
    )

    assert status_response.status_code == 302
    assert note_response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Quoted"
        assert quote_request.notes[0].note_text == "Reviewed photos and prepared pricing draft."