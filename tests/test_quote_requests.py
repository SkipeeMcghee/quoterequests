from __future__ import annotations

from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import QuoteRequest, RequestNote
from app.models.user import User


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_quote_request_page_renders(client):
    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Tell us about your project" in body
    assert "Full name" in body
    assert "Location" in body


def test_quote_request_services_does_not_require_every_checkbox(client):
    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "name=\"services\"" in body
    assert "required type=\"checkbox\"" not in body


def test_quote_request_does_not_show_scheduling_fields(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.get("/quote-request")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" not in body
    assert "Additional Notes" in body


def test_schedule_work_button_visible_in_index_when_scheduling_enabled(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Schedule some work" in body
    assert "/schedule-work" in body


def test_schedule_work_page_renders_scheduling_fields(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.get("/schedule-work")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" in body
    assert "Additional Notes" in body


def test_schedule_work_submission_records_work_request_type(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.post(
        "/schedule-work",
        data={
            "full_name": "Taylor Grant",
            "phone": "555-333-2222",
            "services": ["Inspection"],
            "city": "14 Maple Ln",
            "preferred_date": "2026-05-15",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.request_type == "Work request"


def test_admin_request_detail_shows_status_form_and_submission_time(client, app, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "services": ["Painting"],
            "city": "77 Market St",
        },
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
    assert "Submitted" in body
    assert "Request status" in body
    assert "name=\"status\"" in body
    assert "Request type" not in body


def test_admin_request_detail_shows_last_contacted_field(client, app, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "services": ["Painting"],
            "city": "77 Market St",
        },
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
    assert "Last contacted on" in body
    assert "name=\"last_contacted_on\"" in body


def test_admin_can_edit_and_delete_own_internal_note(client, app, admin_user):
    client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "services": ["Painting"],
            "city": "77 Market St",
        },
        follow_redirects=False,
    )
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )
    client.post(
        "/admin/requests/1/notes",
        data={"note_text": "Initial internal note."},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/notes/1/edit",
        data={"edit-note-1-note_text": "Updated internal note."},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        note = RequestNote.query.one()
        assert note.note_text == "Updated internal note."

    response = client.post(
        "/admin/notes/1/delete",
        data={},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        assert RequestNote.query.count() == 0


def test_quote_request_validation_errors_do_not_save_request(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "",
            "phone": "",
            "email": "",
            "services": [],
            "city": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "This field is required." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_public_quote_request_submission_creates_request(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Jordan Harper",
            "phone": "555-111-2222",
            "services": ["Landscape Design"],
            "city": "123 Garden St",
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
            "services": ["Roof Repair"],
            "city": "45 Cedar Ave",
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


def test_upload_more_than_twenty_photos_is_rejected(client, app):
    photo_data = [(BytesIO(JPEG_BYTES), f"photo{i}.jpg") for i in range(21)]
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Jordan Harper",
            "phone": "555-111-2222",
            "services": ["Landscape Design"],
            "city": "123 Garden St",
            "photos": photo_data,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "You can upload up to 20 photos." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_invalid_upload_type_is_rejected(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Taylor Reed",
            "phone": "555-000-1212",
            "services": ["Window Cleaning"],
            "city": "88 Pine St",
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
            "services": ["Inspection"],
            "city": "17 Walnut Ave",
            "photos": [(BytesIO(b"not-a-real-jpeg"), "fake.jpg")],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "content does not match a supported image type." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_multiple_image_uploads_are_accepted(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Multi Image",
            "phone": "555-121-1212",
            "services": ["Inspection"],
            "city": "17 Walnut Ave",
            "photos": [
                (BytesIO(PNG_BYTES), "deck.png"),
                (BytesIO(JPEG_BYTES), "yard.jpg"),
            ],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert QuoteRequest.query.count() == 1
        assert len(QuoteRequest.query.first().photos) == 2


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
            "services": ["Painting"],
            "city": "55 Cedar Way",
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
            "services": ["Deck Staining"],
            "city": "18 Oak Lane",
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
            "services": ["Flooring"],
            "city": "14 Birch Rd",
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
            "services": ["Siding"],
            "city": "1 First St",
        },
        follow_redirects=False,
    )
    client.post(
        "/quote-request",
        data={
            "full_name": "Second Request",
            "phone": "555-100-0002",
            "services": ["Fence Repair"],
            "city": "2 Second St",
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
            "services": ["Painting"],
            "city": "77 Market St",
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
        assert quote_request.last_contacted_on.isoformat() == __import__('datetime').date.today().isoformat()
        assert quote_request.notes[0].note_text == "Reviewed photos and prepared pricing draft."


def test_scheduling_fields_are_hidden_when_disabled(client, app, admin_user):
    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" not in body
    assert "Additional Notes" in body

    client.post(
        "/quote-request",
        data={
            "full_name": "Skyler Kent",
            "phone": "555-222-3333",
            "services": ["Inspection"],
            "city": "99 Maple Blvd",
        },
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
    assert "Scheduling" not in body


def test_quote_request_does_not_create_appointment_when_scheduling_disabled(client, app):
    response = client.post(
        "/quote-request",
        data={
            "full_name": "Nova Lane",
            "email": "nova@example.com",
            "services": ["Roof Repair"],
            "city": "141 Elm St",
            "preferred_date": "2026-05-01",
            "preferred_time_window": "10am - 2pm",
            "additional_notes": "Please call before arrival.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.full_name == "Nova Lane"
        assert quote_request.appointments == []


def test_quote_request_creates_appointment_when_scheduling_enabled(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.get("/quote-request")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" not in body
    assert "Additional Notes" in body

    response = client.get("/schedule-work")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" in body
    assert "Additional Notes" in body

    response = client.post(
        "/schedule-work",
        data={
            "full_name": "Ari Grant",
            "email": "ari@example.com",
            "services": ["Deck Staining"],
            "city": "202 Garden Path",
            "preferred_date": "2026-06-10",
            "preferred_time_window": "8am - 11am",
            "additional_notes": "Please send a confirmation email.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert len(quote_request.appointments) == 1
        appointment = quote_request.appointments[0]
        assert appointment.status == "Requested"
        assert appointment.requested_date.isoformat() == "2026-06-10"
        assert appointment.requested_time_window == "8am - 11am"
        assert appointment.internal_notes == "Please send a confirmation email."