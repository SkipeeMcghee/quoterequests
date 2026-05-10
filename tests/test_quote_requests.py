from __future__ import annotations

from datetime import date, time
from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import Customer, QuoteRequest, RequestNote, RequestPhoto, RequestQuote
from app.models.user import User
from app.services.recaptcha import RecaptchaVerificationResult


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_quote_request_page_renders(client):
    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Tell us about your project" in body
    assert "Full name" in body
    assert "Location" in body


def test_quote_request_page_renders_recaptcha_v3_when_enabled(client, app):
    app.config["RECAPTCHA_ENABLED"] = True
    app.config["RECAPTCHA_SITE_KEY"] = "test-site-key"
    app.config["RECAPTCHA_SECRET_KEY"] = "test-secret-key"

    response = client.get("/quote-request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'https://www.google.com/recaptcha/api.js?render=test-site-key' in body
    assert 'data-recaptcha-site-key="test-site-key"' in body
    assert 'data-recaptcha-action="quote_request"' in body
    assert 'Protected by reCAPTCHA v3' in body


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
    assert "Schedule Some Work" in body
    assert "/schedule-work" in body


def test_schedule_work_page_renders_scheduling_fields(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    response = client.get("/schedule-work")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Preferred date" in body
    assert "Additional Notes" in body


def test_schedule_work_page_uses_schedule_work_recaptcha_action(client, app):
    app.config["ENABLE_SCHEDULING"] = True
    app.config["RECAPTCHA_ENABLED"] = True
    app.config["RECAPTCHA_SITE_KEY"] = "test-site-key"
    app.config["RECAPTCHA_SECRET_KEY"] = "test-secret-key"

    response = client.get("/schedule-work")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-recaptcha-action="schedule_work"' in body


def test_quote_request_submission_requires_valid_recaptcha_when_enabled(client, app, monkeypatch):
    app.config["RECAPTCHA_ENABLED"] = True
    app.config["RECAPTCHA_SITE_KEY"] = "test-site-key"
    app.config["RECAPTCHA_SECRET_KEY"] = "test-secret-key"
    monkeypatch.setattr(
        "app.main.routes.verify_recaptcha_submission",
        lambda token, action, remote_ip=None: RecaptchaVerificationResult(
            success=False,
            message="We couldn't verify the spam protection check. Please try again.",
        ),
    )

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Taylor Grant",
            "phone": "555-333-2222",
            "services": ["Inspection"],
            "city": "14 Maple Ln",
            "recaptcha_token": "test-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "We couldn't verify the spam protection check. Please try again." in body

    with app.app_context():
        assert QuoteRequest.query.count() == 0


def test_quote_request_submission_succeeds_with_recaptcha_when_enabled(client, app, monkeypatch):
    app.config["RECAPTCHA_ENABLED"] = True
    app.config["RECAPTCHA_SITE_KEY"] = "test-site-key"
    app.config["RECAPTCHA_SECRET_KEY"] = "test-secret-key"
    monkeypatch.setattr(
        "app.main.routes.verify_recaptcha_submission",
        lambda token, action, remote_ip=None: RecaptchaVerificationResult(
            success=True,
            score=0.9,
            action=action,
        ),
    )

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Taylor Grant",
            "phone": "555-333-2222",
            "services": ["Inspection"],
            "city": "14 Maple Ln",
            "recaptcha_token": "test-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/thank-you")

    with app.app_context():
        assert QuoteRequest.query.count() == 1


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


def test_quote_and_work_requests_get_separate_request_numbers(client, app):
    app.config["ENABLE_SCHEDULING"] = True

    quote_response = client.post(
        "/quote-request",
        data={
            "full_name": "Jordan Harper",
            "phone": "555-111-2222",
            "services": ["Landscape Design"],
            "city": "123 Garden St",
        },
        follow_redirects=False,
    )
    work_response = client.post(
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

    assert quote_response.status_code == 302
    assert work_response.status_code == 302

    with app.app_context():
        quote_requests = QuoteRequest.query.order_by(QuoteRequest.id.asc()).all()
        assert len(quote_requests) == 2

        quote_request = next(request for request in quote_requests if request.request_type == "Quote request")
        work_request = next(request for request in quote_requests if request.request_type == "Work request")

        assert quote_request.request_number == 1
        assert work_request.request_number == 1
        assert quote_request.request_reference == "Quote Request #1"
        assert work_request.request_reference == "Work Request #1"


def test_admin_request_detail_shows_automatic_status_and_marks_request_viewed(client, app, admin_user):
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
    assert "name=\"status\"" not in body
    assert "Viewed" in body
    assert "Quote tracking" in body
    assert "Request type" in body
    assert "Quote request" in body

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Viewed"
        assert quote_request.first_viewed_at is not None


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


def test_request_detail_scheduling_minute_dropdowns_default_to_00(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

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
    assert 'create-start_time_minute' in body
    assert 'create-end_time_minute' in body
    assert '<option selected value="0">00</option>' in body


def test_last_contacted_date_updates_request_status_to_contacted(client, app, admin_user):
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

    response = client.post(
        "/admin/requests/1/last-contacted",
        data={"last_contacted_on": date.today().isoformat()},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Contacted"
        assert quote_request.last_contacted_on == date.today()


def test_admin_calendar_and_day_add_work_links_visible_when_enabled(client, app, admin_user):
    app.config["ENABLE_CALENDAR"] = True
    app.config["ENABLE_SCHEDULING"] = True

    client.post(
        "/quote-request",
        data={
            "full_name": "Ari Blake",
            "phone": "555-444-7777",
            "services": ["Painting"],
            "city": "32 Broad St",
        },
        follow_redirects=False,
    )
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/calendar")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Add Work" in body
    assert "/admin/scheduled-work/new?source=calendar" in body

    response = client.get("/admin/calendar/2026/05/01")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Add Work" in body
    assert "/admin/scheduled-work/new?source=day&amp;date=2026-05-01&amp;year=2026&amp;month=5&amp;day=1" in body


def test_admin_customer_detail_schedule_work_button_visible_when_enabled(client, app, admin_user):
    app.config["ENABLE_CUSTOMER_RECORDS"] = True
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        from app.models import Customer

        customer = Customer(primary_name="Test Customer", primary_city="Test City", primary_email="test@example.com")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/customers/{customer_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Schedule Work" in body
    assert f"/admin/scheduled-work/new?customer_id={customer.id}&amp;source=customer" in body


def test_admin_new_scheduled_work_prefills_request_and_date(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/scheduled-work/new?request_id={request_id}&source=request&date=2026-05-10")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "name=\"scheduled-work-request_id\"" in body
    assert f"value=\"{request_id}\"" in body
    assert "name=\"scheduled-work-scheduled_date\"" in body
    assert "value=\"2026-05-10\"" in body
    assert 'data-customer-combobox-input="true"' in body
    assert 'id="scheduled-work-customer_lookup-options"' in body
    assert 'placeholder="Choose an existing customer"' in body
    assert "name=\"scheduled-work-status\"" not in body
    assert "Source request" in body
    assert "Selected date" in body
    assert "Services" in body


def test_admin_new_scheduled_work_supports_services_and_staff_selection(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True
    app.config["ENABLE_STAFF_MANAGEMENT"] = True

    with app.app_context():
        from app.models import ServiceOption, StaffMember

        service = ServiceOption(name="Window Cleaning")
        staff_member = StaffMember(display_name="Alex Crew", worker_type="employee", status="active", services=[service])
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
            services=[service],
        )
        db.session.add_all([service, staff_member, quote_request])
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/scheduled-work/new?request_id={request_id}&source=request")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Services" in body
    assert "Assigned staff" in body
    assert "Window Cleaning" in body
    assert "Alex Crew" in body


def test_admin_request_detail_routes_scheduling_into_shared_scheduled_work_flow(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Schedule this request here without leaving the review workflow." in body
    assert f'action="/admin/requests/{request_id}/appointments"' in body
    assert f"/admin/scheduled-work/new?request_id={request_id}&amp;source=request" not in body


def test_request_detail_can_schedule_inline_and_link_existing_customer(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True
    app.config["ENABLE_CUSTOMER_RECORDS"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.flush()
        request_id = quote_request.id
        customer = Customer(primary_name="Ari Blake", primary_city="32 Broad St", primary_phone="555-444-7777")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/requests/{request_id}/appointments",
        data={
            "create-customer_id": str(customer_id),
            "create-title": "Paint consultation",
            "create-scheduled_date": "2026-05-10",
            "create-start_time_hour": "10",
            "create-start_time_minute": "0",
            "create-end_time_hour": "11",
            "create-end_time_minute": "30",
            "create-submit": "Schedule Event",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/requests/{request_id}#scheduling")

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.customer_id == customer_id
        assert quote_request.status == "Scheduled"
        assert quote_request.current_appointment is not None
        assert quote_request.current_appointment.title == "Paint consultation"
    
def test_request_detail_inline_scheduler_defaults_minutes_to_00_and_uses_event_notes(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    scheduling_section = body.split('id="scheduling"', 1)[1].split('</article>', 1)[0]
    assert 'id="create-start_time_minute" name="create-start_time_minute"><option value="">Minute</option><option selected value="0">00</option>' in body
    assert 'id="create-end_time_minute" name="create-end_time_minute"><option value="">Minute</option><option selected value="0">00</option>' in body
    assert "Event notes" in scheduling_section
    assert "Customer notes" not in scheduling_section
    assert "Internal notes" not in scheduling_section


def test_request_detail_shows_inline_edit_form_for_current_appointment(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.flush()

        from app.models import Appointment
        from datetime import date, time

        appointment = Appointment(
            quote_request_id=quote_request.id,
            title="Paint consultation",
            scheduled_date=date(2026, 5, 10),
            start_time=time(10, 0),
            end_time=time(11, 30),
            status="Scheduled",
        )
        quote_request.appointments.append(appointment)
        db.session.commit()
        request_id = quote_request.id
        appointment_id = appointment.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Keep the scheduled event current here and open the full event page only when you need deeper tools." in body
    assert f'action="/admin/appointments/{appointment_id}/edit?return_to=request"' in body
    assert f'action="/admin/appointments/{appointment_id}/delete?return_to=request"' in body
    assert 'data-confirm-text="Delete Paint consultation?"' in body
    assert 'name="edit-status"' not in body
    assert f"View scheduled event #{appointment_id}" in body
    assert "Open day agenda" in body
    assert "<dt>Agenda</dt>" not in body


def test_request_detail_can_update_assigned_staff_for_current_appointment(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True
    app.config["ENABLE_STAFF_MANAGEMENT"] = True

    with app.app_context():
        from app.models import Appointment, AppointmentStaffAssignment, StaffMember

        customer = Customer(
            primary_name="Ari Blake",
            primary_email="ari@example.com",
            primary_phone="555-444-7777",
            primary_city="32 Broad St",
        )
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            email="ari@example.com",
            city="32 Broad St",
            customer=customer,
        )
        appointment = Appointment(
            quote_request=quote_request,
            customer=customer,
            title="Paint consultation",
            scheduled_date=date(2026, 5, 10),
            start_time=time(10, 0),
            end_time=time(11, 30),
            status="Scheduled",
        )
        staff_one = StaffMember(display_name="Alex Assign", worker_type="employee", status="active")
        staff_two = StaffMember(display_name="Morgan Assign", worker_type="employee", status="active")
        db.session.add_all([customer, quote_request, appointment, staff_one, staff_two])
        db.session.flush()
        db.session.add_all(
            [
                AppointmentStaffAssignment(appointment_id=appointment.id, staff_member_id=staff_one.id),
                AppointmentStaffAssignment(appointment_id=appointment.id, staff_member_id=staff_two.id),
            ]
        )
        db.session.commit()
        request_id = quote_request.id
        appointment_id = appointment.id
        staff_one_id = staff_one.id
        staff_two_id = staff_two.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'action="/admin/appointments/{appointment_id}/assign-staff?return_to=request"' in body
    assert "Alex Assign" in body
    assert "Morgan Assign" in body
    assert "Unavailable" in body
    assert "Save Staff Assignment" not in body

    response = client.post(
        f"/admin/appointments/{appointment_id}/assign-staff?return_to=request",
        data={
            "assign-staff-staff_ids": [str(staff_two_id)],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Alex Assign" in body
    assert "Morgan Assign" in body

    with app.app_context():
        from app.models import Appointment

        appointment = db.session.get(Appointment, appointment_id)
        assigned_staff_ids = sorted(assignment.staff_member_id for assignment in appointment.staff_assignments)
        assert assigned_staff_ids == [staff_two_id]


def test_request_detail_can_delete_current_appointment(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        from app.models import Appointment
        from datetime import date, time

        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.flush()

        appointment = Appointment(
            quote_request_id=quote_request.id,
            title="Paint consultation",
            scheduled_date=date(2026, 5, 10),
            start_time=time(10, 0),
            end_time=time(11, 30),
            status="Scheduled",
        )
        quote_request.appointments.append(appointment)
        db.session.commit()
        request_id = quote_request.id
        appointment_id = appointment.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/appointments/{appointment_id}/delete?return_to=request",
        data={"delete-appointment-submit": "Delete"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/requests/{request_id}#scheduling")

    with app.app_context():
        from app.models import Appointment

        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request is not None
        assert quote_request.current_appointment is None
        assert db.session.get(Appointment, appointment_id) is None


def test_request_detail_inline_edit_returns_to_request_page(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        db.session.add(quote_request)
        db.session.flush()

        from app.models import Appointment
        from datetime import date, time

        appointment = Appointment(
            quote_request_id=quote_request.id,
            title="Paint consultation",
            scheduled_date=date(2026, 5, 10),
            start_time=time(10, 0),
            end_time=time(11, 30),
            status="Scheduled",
        )
        quote_request.appointments.append(appointment)
        db.session.commit()
        request_id = quote_request.id
        appointment_id = appointment.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/appointments/{appointment_id}/edit?return_to=request",
        data={
            "edit-title": "Paint consultation updated",
            "edit-scheduled_date": "2026-05-12",
            "edit-start_time_hour": "12",
            "edit-start_time_minute": "0",
            "edit-end_time_hour": "13",
            "edit-end_time_minute": "30",
            "edit-submit": "Save Scheduling Changes",
        },
        follow_redirects=False,
    )

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.current_appointment is not None
        assert quote_request.current_appointment.title == "Paint consultation updated"


def test_admin_calendar_view_and_list_view_render_as_alternates(client, app, admin_user):
    app.config["ENABLE_CALENDAR"] = True
    app.config["ENABLE_SCHEDULING"] = True

    client.post(
        "/quote-request",
        data={
            "full_name": "Ari Blake",
            "phone": "555-444-7777",
            "services": ["Painting"],
            "city": "32 Broad St",
        },
        follow_redirects=False,
    )

    with app.app_context():
        from app.models import Appointment
        from datetime import date, time

        appointment = Appointment(
            quote_request_id=1,
            title="Morning prep",
            scheduled_date=date(2026, 5, 12),
            start_time=time(8, 0),
            end_time=time(9, 0),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.commit()

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/calendar?year=2026&month=5")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Calendar View" in body
    assert "Upcoming scheduled events" not in body

    response = client.get("/admin/calendar?year=2026&month=5&view=list")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Upcoming scheduled events" in body
    assert "Sorted from soonest to latest by default." in body
    assert "Update List" in body
    assert "Open Day Agenda" not in body


def test_admin_day_agenda_and_appointment_detail_preserve_schedule_navigation(client, app, admin_user):
    app.config["ENABLE_CALENDAR"] = True
    app.config["ENABLE_SCHEDULING"] = True

    client.post(
        "/quote-request",
        data={
            "full_name": "Ari Blake",
            "phone": "555-444-7777",
            "services": ["Painting"],
            "city": "32 Broad St",
        },
        follow_redirects=False,
    )

    with app.app_context():
        from app.models import Appointment
        from datetime import date, time

        appointment = Appointment(
            quote_request_id=1,
            title="Morning prep",
            scheduled_date=date(2026, 5, 12),
            start_time=time(8, 0),
            end_time=time(9, 0),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.commit()
        appointment_id = appointment.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/calendar/2026/5/12")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Today at a glance" in body
    assert f"/admin/appointments/{appointment_id}?source=day&amp;date=2026-05-12&amp;year=2026&amp;month=5&amp;day=12" in body
    assert "/admin/calendar?year=2026&amp;month=5&amp;view=list&amp;show=upcoming&amp;status=all&amp;staff_id=0&amp;sort=soonest" in body

    response = client.get(
        f"/admin/appointments/{appointment_id}?source=calendar&year=2026&month=5&view=list&show=upcoming&status=all&staff_id=0&sort=soonest"
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Back to List View" in body
    assert "Open Calendar View" in body
    assert "Open List View" in body
    assert "Open Day Agenda" in body


def test_admin_can_edit_and_delete_own_internal_note(client, app, admin_user):
    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Casey Blake",
            phone="555-444-9999",
            city="77 Market St",
            request_type="Painting",
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )
    client.post(
        f"/admin/requests/{request_id}/notes",
        data={"note_text": "Initial internal note."},
        follow_redirects=False,
    )

    with app.app_context():
        note = RequestNote.query.one()
        note_id = note.id

    response = client.get(f"/admin/requests/{request_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'class="note-action-link note-edit-toggle"' in body
    assert 'aria-label="Delete note"' in body
    assert 'inline-remove-button inline-remove-button--bare' in body
    assert 'btn btn-secondary btn-small note-edit-toggle' not in body
    assert '>Delete</button>' not in body

    response = client.post(
        f"/admin/notes/{note_id}/edit",
        data={f"edit-note-{note_id}-note_text": "Updated internal note."},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        note = RequestNote.query.one()
        assert note.note_text == "Updated internal note."

    response = client.post(
        f"/admin/notes/{note_id}/delete",
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
    assert "Submit Another Request" in body


def test_uploaded_files_appear_on_admin_request_detail_page(client, app, admin_user):
    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Avery Stone",
            phone="555-343-2222",
            city="18 Oak Lane",
        )
        db.session.add(quote_request)
        db.session.flush()
        request_id = quote_request.id
        db.session.add_all(
            [
                RequestPhoto(
                    quote_request=quote_request,
                    file_path=f"uploads/quote_requests/{request_id}/deck-front.png",
                ),
                RequestPhoto(
                    quote_request=quote_request,
                    file_path=f"uploads/quote_requests/{request_id}/deck-side.png",
                ),
            ]
        )
        db.session.commit()

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Photo gallery" in body
    assert "Browse each uploaded image in place" in body
    assert 'data-photo-gallery' in body
    assert 'data-gallery-stage' in body
    assert 'data-gallery-prev' in body
    assert 'data-gallery-next' in body
    assert body.count('aria-label="Show quote request photo ') == 2
    assert 'activeIndex = (activeIndex - 1 + thumbButtons.length) % thumbButtons.length;' in body
    assert 'activeIndex = (activeIndex + 1) % thumbButtons.length;' in body
    assert f"/static/uploads/quote_requests/{request_id}/" in body
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
    assert "Request queue" in body
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


def test_dashboard_uses_simplified_admin_header(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get("/admin/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert ">Public Site</a>" in body
    assert 'href="/quote-request"' not in body
    assert 'href="/schedule-work"' not in body
    assert ">Dashboard</a>" not in body
    assert ">Requests</a>" in body
    assert "Logout" in body


def test_request_detail_uses_shared_admin_header_and_back_link(client, app, admin_user):
    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Morgan Detail",
            phone="555-333-2222",
            email="morgan@example.com",
            city="19 Elm St",
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.count("dashboard-actions admin-nav-buttons") == 1
    assert ">Public Site</a>" in body
    assert ">Back to Requests</a>" in body
    assert "Morgan Detail" in body
    assert "Submitted" in body
    assert 'admin-page-header__meta' not in body
    assert 'href="/quote-request"' not in body
    assert 'href="/schedule-work"' not in body


def test_request_detail_shows_compact_linked_customer_summary(client, app, admin_user):
    app.config["ENABLE_CUSTOMER_RECORDS"] = True

    with app.app_context():
        customer = Customer(
            primary_name="Jordan Avery",
            primary_email="jordan@example.com",
            primary_phone="555-010-1212",
            primary_city="Pine Grove",
        )
        quote_request = QuoteRequest(
            full_name="Jordan Avery",
            phone="555-010-1212",
            email="jordan@example.com",
            city="Pine Grove",
            customer=customer,
        )
        db.session.add_all([customer, quote_request])
        db.session.commit()
        request_id = quote_request.id
        customer_id = customer.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Linked:" in body
    assert 'id="customer-matching"' in body
    assert f'href="/admin/customers/{customer_id}"' in body
    assert ">Jordan Avery</a>" in body
    assert ">Request details</h2>" in body
    assert "View Customer" not in body
    assert "Customer account" not in body
    assert "customer-link-panel--linked" not in body
    assert f'action="/admin/requests/{request_id}/unlink-customer"' in body
    assert 'aria-label="Unlink customer"' in body
    assert '<div class="customer-link-inline">' in body
    assert 'inline-remove-button inline-remove-button--bare' in body


def test_request_detail_can_unlink_linked_customer(client, app, admin_user):
    app.config["ENABLE_CUSTOMER_RECORDS"] = True

    with app.app_context():
        from app.models import Appointment

        customer = Customer(
            primary_name="Jordan Avery",
            primary_email="jordan@example.com",
            primary_phone="555-010-1212",
            primary_city="Pine Grove",
        )
        quote_request = QuoteRequest(
            full_name="Jordan Avery",
            phone="555-010-1212",
            email="jordan@example.com",
            city="Pine Grove",
            customer=customer,
        )
        appointment = Appointment(
            quote_request=quote_request,
            customer=customer,
            title="Initial walkthrough",
            scheduled_date=date(2026, 5, 10),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status="Scheduled",
        )
        db.session.add_all([customer, quote_request, appointment])
        db.session.commit()
        request_id = quote_request.id
        appointment_id = appointment.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/requests/{request_id}/unlink-customer",
        data={},
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Customer account" in body
    assert "Linked:" not in body

    with app.app_context():
        from app.models import Appointment

        quote_request = db.session.get(QuoteRequest, request_id)
        appointment = db.session.get(Appointment, appointment_id)
        assert quote_request.customer_id is None
        assert appointment.customer_id is None


def test_request_detail_can_link_existing_customer_from_combobox(client, app, admin_user):
    app.config["ENABLE_CUSTOMER_RECORDS"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Ari Blake",
            phone="555-444-7777",
            city="32 Broad St",
        )
        customer = Customer(
            primary_name="Ari Blake",
            primary_phone="555-444-7777",
            primary_city="32 Broad St",
        )
        db.session.add_all([quote_request, customer])
        db.session.commit()
        request_id = quote_request.id
        customer_id = customer.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/requests/{request_id}/link-customer",
        data={
            "link-customer-manual_customer_lookup": "Ari Blake — no email — 555-444-7777",
            "link-customer-manual_customer_id": str(customer_id),
            "link-customer-submit": "Manual Link",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/requests/{request_id}#customer-matching")

    with app.app_context():
        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request.customer_id == customer_id


def test_request_detail_includes_scroll_restore_targets_for_inline_forms(client, app, admin_user):
    app.config.update(ENABLE_CUSTOMER_RECORDS=True, ENABLE_SCHEDULING=True)

    with app.app_context():
        customer = Customer(
            primary_name="Taylor Flow",
            primary_phone="555-777-1111",
            primary_email="taylor@example.com",
            primary_city="12 Oak Ave",
        )
        quote_request = QuoteRequest(
            full_name="Taylor Flow",
            phone="555-777-1111",
            email="taylor@example.com",
            city="12 Oak Ave",
        )
        db.session.add_all([customer, quote_request])
        db.session.commit()
        request_id = quote_request.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.get(f"/admin/requests/{request_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="customer-matching"' in body
    assert 'id="request-detail-customer-panel"' in body
    assert 'id="request-detail-customer-field"' in body
    assert 'id="request-detail-scheduling-region"' in body
    assert 'id="request-details"' in body
    assert 'id="quotes"' in body
    assert 'id="notes"' in body
    assert "Link this request to an existing customer or create a new one here." in body
    assert "Create a new customer from this request." in body
    assert body.count('data-customer-combobox-input="true"') == 2
    assert 'data-customer-id-input="true"' in body
    assert 'class="customer-combobox__panel" id="manual-customer-options"' in body
    assert 'id="create-customer_lookup-options"' in body
    assert 'data-customer-option' in body
    assert 'placeholder="Click here to manually link by searching for an existing customer."' in body
    assert 'placeholder="Choose an existing customer"' in body
    assert '<p class="customer-link-section-text">Click here to manually link by searching for an existing customer.</p>' not in body
    assert body.count('class="contact-or customer-link-or"') == 2
    assert ">Auto Link<" in body
    assert ">Manual Link<" in body
    assert ">Add Customer<" in body
    assert "Select an existing customer if the right match is not listed." not in body
    assert "Type a name, email, or phone number" not in body
    assert "Type to narrow the list as you search." not in body
    assert "Link this request to an existing customer or create a new internal customer account." not in body
    assert "Existing customer matches were found for this request. Confirm a link or select another record." not in body
    assert 'data-scroll-anchor="customer-matching"' in body
    assert 'data-request-detail-refresh="true"' in body
    assert 'data-scroll-anchor="request-details"' in body
    assert 'data-scroll-anchor="quotes"' in body
    assert 'data-scroll-anchor="notes"' in body
    assert "admin-request-detail-scroll" in body
    assert "request-detail-customer-panel" in body


def test_login_page_renders(client):
    response = client.get("/admin")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Admin access" in body
    assert "Password" in body
    assert "Home" not in body


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
    assert "/admin?next=%2Fadmin%2F" in response.headers["Location"]


def test_login_redirects_to_requested_admin_page(client, admin_user):
    login_page = client.get("/admin?next=/admin/")
    assert login_page.status_code == 200

    response = client.post(
        "/admin?next=/admin/",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/")


def test_logout_works_and_admin_routes_are_protected_after_logout(client, admin_user):
    client.post(
        "/admin",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    logout_response = client.post("/auth/logout", follow_redirects=False)
    protected_response = client.get("/admin/", follow_redirects=False)

    assert logout_response.status_code == 302
    assert logout_response.headers["Location"].endswith("/admin")
    assert protected_response.status_code == 302
    assert "/admin?next=%2Fadmin%2F" in protected_response.headers["Location"]


def test_legacy_login_routes_redirect_to_admin(client):
    auth_login = client.get("/auth/login", follow_redirects=False)
    login = client.get("/login", follow_redirects=False)
    dashboard_login = client.get("/dashboard/login", follow_redirects=False)

    assert auth_login.status_code == 302
    assert auth_login.headers["Location"].endswith("/admin")
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/admin")
    assert dashboard_login.status_code == 302
    assert dashboard_login.headers["Location"].endswith("/admin")


def test_create_dev_admin_command_creates_first_admin(app):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["create-dev-admin", "--email", "devadmin@example.com", "--password", "LocalPass123!"])

    assert result.exit_code == 0
    assert "Development admin user created." in result.output

    with app.app_context():
        user = User.query.filter_by(email="devadmin@example.com").first()
        assert user is not None
        assert user.check_password("LocalPass123!") is True


def test_admin_can_add_quote_and_note(client, app, admin_user):
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

    quote_response = client.post(
        "/admin/requests/1/quotes",
        data={
            "request-quote-amount": "2450.00",
            "request-quote-billing_frequency": "Weekly",
            "request-quote-description": "Exterior repaint option",
            "request-quote-submit": "Add Quote",
        },
        follow_redirects=False,
    )
    note_response = client.post(
        "/admin/requests/1/notes",
        data={"note_text": "Reviewed photos and prepared pricing draft."},
        follow_redirects=False,
    )

    assert quote_response.status_code == 302
    assert note_response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Quoted"
        assert quote_request.last_contacted_on is None
        assert quote_request.quotes[0].amount == 2450
        assert quote_request.quotes[0].billing_frequency == "Weekly"
        assert quote_request.quotes[0].description == "Exterior repaint option"
        assert quote_request.notes[0].note_text == "Reviewed photos and prepared pricing draft."


def test_quote_status_dropdown_updates_request_status(client, app, admin_user):
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
        "/admin/requests/1/quotes",
        data={
            "request-quote-amount": "1850.00",
            "request-quote-billing_frequency": "Monthly",
            "request-quote-description": "Interior repaint option",
            "request-quote-submit": "Add Quote",
        },
        follow_redirects=False,
    )

    with app.app_context():
        request_quote = RequestQuote.query.one()
        quote_id = request_quote.id

    accept_response = client.post(
        f"/admin/quotes/{quote_id}/decision",
        data={
            f"quote-decision-{quote_id}-decision": "Accepted",
            f"quote-decision-{quote_id}-submit": "Save Decision",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Accepted"
        assert quote_request.quotes[0].decision == "Accepted"
        assert quote_request.quotes[0].billing_frequency == "Monthly"

    reject_response = client.post(
        f"/admin/quotes/{quote_id}/decision",
        data={
            f"quote-decision-{quote_id}-decision": "Rejected",
            f"quote-decision-{quote_id}-submit": "Save Decision",
        },
        follow_redirects=False,
    )
    assert reject_response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Rejected"
        assert quote_request.quotes[0].decision == "Rejected"


def test_quote_status_update_route_returns_json_for_ajax_requests(client, app, admin_user):
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
        "/admin/requests/1/quotes",
        data={
            "request-quote-amount": "1850.00",
            "request-quote-billing_frequency": "Monthly",
            "request-quote-description": "Interior repaint option",
            "request-quote-submit": "Add Quote",
        },
        follow_redirects=False,
    )

    with app.app_context():
        request_quote = RequestQuote.query.one()
        quote_id = request_quote.id

    response = client.post(
        f"/admin/quotes/{quote_id}/decision",
        data={
            f"quote-decision-{quote_id}-decision": "Accepted",
            f"quote-decision-{quote_id}-submit": "Save Decision",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {
        "ok": True,
        "decision": "Accepted",
        "requestStatus": "Accepted",
    }


def test_quote_delete_action_removes_quote_from_request(client, app, admin_user):
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
        "/admin/requests/1/quotes",
        data={
            "request-quote-amount": "1850.00",
            "request-quote-billing_frequency": "Monthly",
            "request-quote-description": "Interior repaint option",
            "request-quote-submit": "Add Quote",
        },
        follow_redirects=False,
    )

    with app.app_context():
        request_quote = RequestQuote.query.one()
        quote_id = request_quote.id

    delete_response = client.post(
        f"/admin/quotes/{quote_id}/delete",
        data={f"delete-quote-{quote_id}-submit": "1"},
        follow_redirects=False,
    )

    assert delete_response.status_code == 302

    with app.app_context():
        quote_request = QuoteRequest.query.one()
        assert quote_request.status == "Viewed"
        assert quote_request.quotes == []


def test_admin_request_detail_shows_billing_frequency_in_quote_tracking(client, app, admin_user):
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
        "/admin/requests/1/quotes",
        data={
            "request-quote-amount": "950.00",
            "request-quote-billing_frequency": "Biweekly",
            "request-quote-description": "Touch-up package",
            "request-quote-submit": "Add Quote",
        },
        follow_redirects=False,
    )

    response = client.get("/admin/requests/1")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Billing frequency" in body
    assert "Biweekly" in body
    assert "Delete quote" in body
    assert 'data-auto-submit-on-change="true"' in body
    assert 'request-quote-item__status-feedback' in body


def test_invalid_csrf_redirects_back_with_message(client, app):
    app.config["WTF_CSRF_ENABLED"] = True

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "services": ["Painting"],
            "city": "77 Market St",
        },
        headers={"Referer": "http://localhost/quote-request"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "security token expired" in body
    assert "Tell us about your project" in body


def test_invalid_csrf_returns_json_for_ajax_requests(client, app):
    app.config["WTF_CSRF_ENABLED"] = True

    response = client.post(
        "/quote-request",
        data={
            "full_name": "Casey Blake",
            "phone": "555-444-9999",
            "services": ["Painting"],
            "city": "77 Market St",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {
        "ok": False,
        "error": "That page sat too long and its security token expired. Reload and try again.",
    }


def test_scheduling_a_request_sets_request_status_to_scheduled(client, app, admin_user):
    app.config["ENABLE_SCHEDULING"] = True
    app.config["ENABLE_CUSTOMER_RECORDS"] = True

    with app.app_context():
        quote_request = QuoteRequest(
            full_name="Casey Blake",
            phone="555-444-9999",
            city="77 Market St",
        )
        db.session.add(quote_request)
        db.session.flush()
        request_id = quote_request.id
        from app.models import Customer

        customer = Customer(primary_name="Casey Blake", primary_city="77 Market St", primary_phone="555-444-9999")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )

    response = client.post(
        f"/admin/scheduled-work/new?request_id={request_id}&source=request",
        data={
            "scheduled-work-request_id": str(request_id),
            "scheduled-work-customer_id": str(customer_id),
            "scheduled-work-title": "Paint consultation",
            "scheduled-work-scheduled_date": "2026-05-10",
            "scheduled-work-start_time_hour": "10",
            "scheduled-work-start_time_minute": "0",
            "scheduled-work-end_time_hour": "11",
            "scheduled-work-end_time_minute": "30",
            "scheduled-work-status": "Scheduled",
            "scheduled-work-submit": "Add Work",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request.status == "Scheduled"


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
            "preferred_time_hour": "10",
            "preferred_time_minute": "0",
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
            "preferred_time_hour": "8",
            "preferred_time_minute": "0",
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
        assert appointment.requested_time == time(8, 0)
        assert appointment.internal_notes == "Please send a confirmation email."