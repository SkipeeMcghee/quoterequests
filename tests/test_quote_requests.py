from __future__ import annotations

from io import BytesIO

from app.models import QuoteRequest


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
            "photos": [(BytesIO(b"fake-image-data"), "yard.jpg")],
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