from __future__ import annotations

from datetime import date, time, timedelta
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

from app.extensions import db
from app.models import (
    Appointment,
    AppointmentStaffAssignment,
    Customer,
    QuoteRequest,
    RecurringWork,
    ServiceOption,
    StaffAvailability,
    StaffMember,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class WorkflowHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []
        self.button_classes: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)

        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])

        if tag not in {"a", "button", "input"}:
            return

        classes = (attributes.get("class") or "").split()
        if any(class_name.startswith("btn") for class_name in classes):
            self.button_classes.append(classes)


def _login_as_admin(client, admin_user: str) -> None:
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def _time_form_data(prefix: str, field_name: str, hour: int, minute: int = 0) -> dict[str, str]:
    return {
        f"{prefix}-{field_name}_hour": str(hour),
        f"{prefix}-{field_name}_minute": str(minute),
    }


def _seed_workflow_context(
    app,
    *,
    scheduled_offset_days: int = 3,
    include_appointment: bool = True,
    include_staff: bool = False,
    include_recurring: bool = False,
    link_request_to_customer: bool = True,
) -> dict[str, object]:
    scheduled_date = date.today() + timedelta(days=scheduled_offset_days)

    with app.app_context():
        service = ServiceOption(name="Window Cleaning")
        other_service = ServiceOption(name="Inspection")
        quote_request = QuoteRequest(
            full_name="Casey Request",
            phone="555-111-2222",
            email="casey@example.com",
            city="Test City",
            services=[service],
        )
        customer = Customer(
            primary_name="Jordan Customer",
            primary_phone="555-333-4444",
            primary_email="jordan@example.com",
            primary_city="Test City",
        )
        if link_request_to_customer:
            quote_request.customer = customer

        db.session.add_all([service, other_service, quote_request, customer])
        db.session.flush()

        appointment = None
        if include_appointment:
            appointment = Appointment(
                customer=customer,
                quote_request=quote_request,
                title="Window visit",
                scheduled_date=scheduled_date,
                start_time=time(9, 0),
                end_time=time(11, 0),
                status="Scheduled",
                customer_notes="Call before arrival.",
                internal_notes="Bring extension ladder.",
            )
            db.session.add(appointment)
            db.session.flush()

        recurring_work = None
        if include_recurring:
            recurring_work = RecurringWork(
                customer=customer,
                quote_request=quote_request,
                title="Monthly window route",
                frequency="weekly",
                day_of_week=scheduled_date.weekday(),
                starts_on=scheduled_date,
                start_time=time(9, 0),
                end_time=time(11, 0),
                status="active",
            )
            db.session.add(recurring_work)
            db.session.flush()

        staff = None
        if include_staff:
            staff = StaffMember(
                display_name="Alex Crew",
                phone="555-777-8888",
                email="alex@example.com",
                role_title="Lead Tech",
                worker_type="employee",
                status="active",
                services=[service],
            )
            db.session.add(staff)
            db.session.flush()
            db.session.add(
                StaffAvailability(
                    staff_member_id=staff.id,
                    day_of_week=scheduled_date.weekday(),
                    start_time=time(8, 0),
                    end_time=time(16, 0),
                )
            )

        db.session.commit()

        return {
            "service_id": service.id,
            "other_service_id": other_service.id,
            "request_id": quote_request.id,
            "customer_id": customer.id,
            "appointment_id": appointment.id if appointment else None,
            "recurring_work_id": recurring_work.id if recurring_work else None,
            "staff_id": staff.id if staff else None,
            "scheduled_date": scheduled_date,
        }


def _assert_button_classes_consistent(body: str) -> None:
    parser = WorkflowHtmlParser()
    parser.feed(body)

    for classes in parser.button_classes:
        assert "btn" in classes

        style_variants = {"btn-primary", "btn-secondary", "btn-danger"}.intersection(classes)
        assert len(style_variants) <= 1

        if "btn-small" in classes:
            assert style_variants


def _assert_internal_links_ok(client, current_url: str, body: str) -> None:
    parser = WorkflowHtmlParser()
    parser.feed(body)

    for href in parser.hrefs:
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        resolved = urljoin(f"http://localhost{current_url}", href)
        parsed = urlparse(resolved)
        if parsed.netloc not in {"localhost", "127.0.0.1", ""}:
            continue

        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"

        response = client.get(target)
        assert response.status_code < 400, f"Broken link {target} from {current_url}"


def _assert_page_contract(
    client,
    url: str,
    *,
    main_nav: bool = False,
    back_label: str | None = None,
    expected_text: tuple[str, ...] = (),
    expected_nav_labels: tuple[str, ...] = ("Requests", "Schedule", "Customers", "Staff", "Recurring Work"),
) -> str:
    response = client.get(url)
    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert body.count("dashboard-actions admin-nav-buttons") == 1

    if main_nav:
        for label in expected_nav_labels:
            assert label in body

    if back_label is not None:
        assert back_label in body

    for text in expected_text:
        assert text in body

    _assert_button_classes_consistent(body)
    _assert_internal_links_ok(client, url, body)
    return body


def test_incoming_request_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_STAFF_MANAGEMENT=True,
    )
    scheduled_date = date.today() + timedelta(days=4)

    with app.app_context():
        service = ServiceOption(name="Window Cleaning")
        quote_request = QuoteRequest(
            full_name="Casey Request",
            phone="555-111-2222",
            email="casey@example.com",
            city="Test City",
            services=[service],
        )
        db.session.add_all([service, quote_request])
        db.session.commit()
        request_id = quote_request.id

    _login_as_admin(client, admin_user)

    _assert_page_contract(
        client,
        "/admin/",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers", "Staff", "Recurring Work"),
    )
    _assert_page_contract(
        client,
        f"/admin/requests/{request_id}",
        back_label="Back to Requests",
        expected_text=("Scheduling", "Customer account", "Schedule this request here without leaving the review workflow."),
    )

    with app.app_context():
        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request is not None
        assert quote_request.status == "Viewed"

    response = client.post(f"/admin/requests/{request_id}/create-customer", data={}, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request is not None
        assert quote_request.customer is not None
        customer_id = quote_request.customer.id

    schedule_url = f"/admin/scheduled-work/new?request_id={request_id}&source=request"
    _assert_page_contract(
        client,
        schedule_url,
        back_label="Back to Request",
        expected_text=("Required scheduling details", "Source request", "After save"),
    )

    response = client.post(
        schedule_url,
        data={
            "scheduled-work-request_id": str(request_id),
            "scheduled-work-customer_id": str(customer_id),
            "scheduled-work-scheduled_date": scheduled_date.isoformat(),
            **_time_form_data("scheduled-work", "start_time", 9),
            **_time_form_data("scheduled-work", "end_time", 11),
            "scheduled-work-customer_notes": "Customer requested an arrival text.",
            "scheduled-work-internal_notes": "Bring ladder.",
            "scheduled-work-submit": "Add Work",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    appointment_detail_url = response.headers["Location"]

    with app.app_context():
        appointment = Appointment.query.one()
        assert appointment.title is None
        assert appointment.customer_id == customer_id
        appointment_id = appointment.id
        quote_request = db.session.get(QuoteRequest, request_id)
        assert quote_request is not None
        assert quote_request.status == "Scheduled"

    appointment_body = _assert_page_contract(
        client,
        appointment_detail_url,
        back_label="Back to Request",
        expected_text=(f"Event #{appointment_id}", "Day View", "Event notes"),
    )
    assert "Reschedule" not in appointment_body
    assert "Customer notes" not in appointment_body

    day_url = f"/admin/calendar/{scheduled_date.year}/{scheduled_date.month:02d}/{scheduled_date.day:02d}"
    day_body = _assert_page_contract(
        client,
        day_url,
        back_label="Back to Calendar View",
        expected_text=("Daily Agenda", f"Event #{appointment_id}"),
    )
    assert f"/admin/appointments/{appointment_id}?source=day" in day_body


def test_customer_record_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
        ENABLE_RECURRING_WORK=True,
    )
    scheduled_date = date.today() + timedelta(days=5)
    recurring_start = date.today() + timedelta(days=7)

    with app.app_context():
        service = ServiceOption(name="Window Cleaning")
        customer = Customer(
            primary_name="Jordan Customer",
            primary_phone="555-333-4444",
            primary_email="jordan@example.com",
            primary_city="Test City",
        )
        quote_request = QuoteRequest(
            full_name="Jordan Customer",
            phone="555-333-4444",
            email="jordan@example.com",
            city="Test City",
            customer=customer,
            services=[service],
        )
        db.session.add_all([service, customer, quote_request])
        db.session.commit()
        customer_id = customer.id

    _login_as_admin(client, admin_user)

    _assert_page_contract(
        client,
        "/admin/customers",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers", "Recurring Work"),
    )
    _assert_page_contract(
        client,
        f"/admin/customers/{customer_id}",
        back_label="Back to Customers",
        expected_text=("Schedule Work", "Add Recurring Work", "Workflow shortcuts", "Upload images"),
    )

    response = client.post(
        f"/admin/customers/{customer_id}/notes",
        data={
            "customer-note-note_text": "Gate code is 4242.",
            "customer-note-submit": "Add Note",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Gate code is 4242." in response.get_data(as_text=True)

    response = client.post(
        f"/admin/customers/{customer_id}/photos",
        data={
            "customer-photos-photos": (BytesIO(PNG_BYTES), "customer.png"),
            "customer-photos-submit": "Upload Photos",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    photo_body = response.get_data(as_text=True)
    assert "/static/uploads/" in photo_body

    customer_schedule_url = f"/admin/scheduled-work/new?customer_id={customer_id}&source=customer"
    _assert_page_contract(
        client,
        customer_schedule_url,
        back_label="Back to Customer",
        expected_text=("Required scheduling details", "Customer", "After save"),
    )

    response = client.post(
        customer_schedule_url,
        data={
            "scheduled-work-request_id": "",
            "scheduled-work-customer_id": str(customer_id),
            "scheduled-work-title": "Customer record visit",
            "scheduled-work-scheduled_date": scheduled_date.isoformat(),
            **_time_form_data("scheduled-work", "start_time", 13),
            **_time_form_data("scheduled-work", "end_time", 15),
            "scheduled-work-submit": "Add Work",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    recurring_url = f"/admin/customers/{customer_id}/recurring-work/new"
    _assert_page_contract(
        client,
        recurring_url,
        back_label="Back to Customer",
        expected_text=("Customer context", "Recurring work details"),
    )

    response = client.post(
        recurring_url,
        data={
            "recurring-work-title": "Monthly customer follow-up",
            "recurring-work-frequency": "weekly",
            "recurring-work-day_of_week": str(recurring_start.weekday()),
            "recurring-work-day_of_month": "0",
            "recurring-work-starts_on": recurring_start.isoformat(),
            "recurring-work-ends_on": "",
            **_time_form_data("recurring-work", "start_time", 9),
            **_time_form_data("recurring-work", "end_time", 10),
            "recurring-work-status": "active",
            "recurring-work-notes": "Morning window preferred.",
            "recurring-work-submit": "Save Recurring Work",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    detail_body = _assert_page_contract(
        client,
        response.headers["Location"],
        back_label="Back to Customer",
        expected_text=("Generate upcoming appointments", "Monthly customer follow-up"),
    )
    assert "Morning window preferred." in detail_body

    with app.app_context():
        customer = db.session.get(Customer, customer_id)
        assert customer is not None
        assert len(customer.notes) == 1
        assert len(customer.photos) == 1
        assert len(customer.appointments) == 1
        assert len(customer.recurring_works) == 1


def test_scheduling_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
    )
    context = _seed_workflow_context(app, include_appointment=False, include_recurring=False, include_staff=False)
    request_id = context["request_id"]
    customer_id = context["customer_id"]
    scheduled_date = context["scheduled_date"]

    _login_as_admin(client, admin_user)

    _assert_page_contract(
        client,
        f"/admin/scheduled-work/new?request_id={request_id}&source=request",
        back_label="Back to Request",
        expected_text=("Source request",),
    )
    _assert_page_contract(
        client,
        f"/admin/scheduled-work/new?customer_id={customer_id}&source=customer",
        back_label="Back to Customer",
        expected_text=("Customer",),
    )
    _assert_page_contract(
        client,
        f"/admin/scheduled-work/new?source=calendar&year={scheduled_date.year}&month={scheduled_date.month}&view=list&show=upcoming&status=all&staff_id=0&sort=soonest",
        back_label="Back to List View",
        expected_text=("Schedule source",),
    )

    day_schedule_url = (
        f"/admin/scheduled-work/new?source=day&date={scheduled_date.isoformat()}&year={scheduled_date.year}"
        f"&month={scheduled_date.month}&day={scheduled_date.day}"
    )
    _assert_page_contract(
        client,
        day_schedule_url,
        back_label="Back to Day Agenda",
        expected_text=("Selected date",),
    )

    response = client.post(
        day_schedule_url,
        data={
            "scheduled-work-request_id": str(request_id),
            "scheduled-work-customer_id": str(customer_id),
            "scheduled-work-scheduled_date": scheduled_date.isoformat(),
            **_time_form_data("scheduled-work", "start_time", 10, 30),
            **_time_form_data("scheduled-work", "end_time", 12),
            "scheduled-work-submit": "Add Work",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        appointment = Appointment.query.order_by(Appointment.id.desc()).first()
        assert appointment is not None
        appointment_id = appointment.id

    _assert_page_contract(
        client,
        "/admin/calendar",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )

    calendar_body = _assert_page_contract(
        client,
        "/admin/calendar?view=calendar",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )
    assert "10:30 AM – 12:00 PM" in calendar_body

    list_body = _assert_page_contract(
        client,
        "/admin/calendar?view=list",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )
    assert f"Event #{appointment_id}" in list_body

    day_body = _assert_page_contract(
        client,
        f"/admin/calendar/{scheduled_date.year}/{scheduled_date.month:02d}/{scheduled_date.day:02d}",
        back_label="Back to Calendar View",
        expected_text=("Daily Agenda", f"Event #{appointment_id}"),
    )
    assert f"date={scheduled_date.isoformat()}" in day_body


def test_calendar_list_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
    )
    context = _seed_workflow_context(app, include_appointment=True, include_recurring=False, include_staff=False)
    appointment_id = context["appointment_id"]
    scheduled_date = context["scheduled_date"]

    _login_as_admin(client, admin_user)

    calendar_body = _assert_page_contract(
        client,
        "/admin/calendar",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )
    assert "9:00 AM – 11:00 AM" in calendar_body

    list_body = _assert_page_contract(
        client,
        "/admin/calendar?view=list",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )
    assert f"Event #{appointment_id}" in list_body

    day_url = f"/admin/calendar/{scheduled_date.year}/{scheduled_date.month:02d}/{scheduled_date.day:02d}"
    day_body = _assert_page_contract(
        client,
        day_url,
        back_label="Back to Calendar View",
        expected_text=("Daily Agenda", f"Event #{appointment_id}"),
    )
    assert f"/admin/appointments/{appointment_id}?source=day" in day_body

    appointment_detail_url = (
        f"/admin/appointments/{appointment_id}?source=day&date={scheduled_date.isoformat()}"
        f"&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}"
    )
    appointment_detail_body = _assert_page_contract(
        client,
        appointment_detail_url,
        back_label="Back to Day Agenda",
        expected_text=(f"Event #{appointment_id}", "Event notes", "History", "Day View"),
    )
    assert "Reschedule" not in appointment_detail_body
    assert "Customer notes" not in appointment_detail_body

    response = client.post(
        (
            f"/admin/appointments/{appointment_id}/edit?source=day&date={scheduled_date.isoformat()}"
            f"&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}"
        ),
        data={
            "edit-scheduled_date": scheduled_date.isoformat(),
            **_time_form_data("edit", "start_time", 11),
            **_time_form_data("edit", "end_time", 13),
            "edit-internal_notes": "Crew lead approved the updated timing.",
            "edit-requested_date": "",
            "edit-requested_time_hour": "",
            "edit-requested_time_minute": "",
            "edit-confirmed_date": "",
            "edit-confirmed_time_hour": "",
            "edit-confirmed_time_minute": "",
            "edit-submit": "Save Changes",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    updated_body = response.get_data(as_text=True)
    assert f"Event #{appointment_id}" in updated_body
    assert "Crew lead approved the updated timing." in updated_body

    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assert appointment is not None
        assert appointment.title is None
        assert appointment.customer_notes == "Call before arrival."
        assert appointment.internal_notes == "Crew lead approved the updated timing."
        assert appointment.status == "Scheduled"

    refreshed_list_body = _assert_page_contract(
        client,
        "/admin/calendar?view=list",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers"),
    )
    assert f"Event #{appointment_id}" in refreshed_list_body

    refreshed_day_body = _assert_page_contract(
        client,
        day_url,
        back_label="Back to Calendar View",
        expected_text=(f"Event #{appointment_id}",),
    )
    assert "Scheduled" in refreshed_day_body


def test_recurring_work_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
        ENABLE_RECURRING_WORK=True,
    )
    context = _seed_workflow_context(app, include_appointment=False, include_recurring=False, include_staff=False)
    customer_id = context["customer_id"]
    request_id = context["request_id"]
    recurring_start = date.today() + timedelta(days=2)

    _login_as_admin(client, admin_user)

    customer_body = _assert_page_contract(
        client,
        f"/admin/customers/{customer_id}",
        back_label="Back to Customers",
        expected_text=("Add Recurring Work", "Open the recurring work directory"),
    )
    assert f"/admin/customers/{customer_id}/recurring-work/new" in customer_body

    recurring_url = f"/admin/customers/{customer_id}/recurring-work/new"
    _assert_page_contract(
        client,
        recurring_url,
        back_label="Back to Customer",
        expected_text=("Customer context", "Recurring work details"),
    )

    response = client.post(
        recurring_url,
        data={
            "recurring-work-title": "Weekly exterior windows",
            "recurring-work-frequency": "weekly",
            "recurring-work-day_of_week": str(recurring_start.weekday()),
            "recurring-work-day_of_month": "0",
            "recurring-work-starts_on": recurring_start.isoformat(),
            "recurring-work-ends_on": "",
            **_time_form_data("recurring-work", "start_time", 8),
            **_time_form_data("recurring-work", "end_time", 10),
            "recurring-work-status": "active",
            "recurring-work-notes": f"Linked request #{request_id}",
            "recurring-work-submit": "Save Recurring Work",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    recurring_detail_url = response.headers["Location"]

    recurring_detail_body = _assert_page_contract(
        client,
        recurring_detail_url,
        back_label="Back to Customer",
        expected_text=("Generate upcoming appointments", "Weekly exterior windows"),
    )
    assert f"Linked request #{request_id}" in recurring_detail_body

    with app.app_context():
        recurring_work = RecurringWork.query.one()
        recurring_work_id = recurring_work.id

    response = client.post(
        f"/admin/recurring-work/{recurring_work_id}/generate?source=customer&customer_id={customer_id}",
        data={
            "generate-recurring-days_ahead": "30",
            "generate-recurring-submit": "Generate Upcoming Appointments",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        appointment = Appointment.query.filter_by(recurring_work_id=recurring_work_id).first()
        assert appointment is not None
        scheduled_date = appointment.scheduled_date
        appointment_id = appointment.id

    generated_detail_body = _assert_page_contract(
        client,
        f"/admin/recurring-work/{recurring_work_id}?source=customer&customer_id={customer_id}",
        back_label="Back to Customer",
        expected_text=("Generated appointments",),
    )
    assert f"/admin/appointments/{appointment_id}?source=day" in generated_detail_body

    recurring_list_body = _assert_page_contract(
        client,
        "/admin/recurring-work",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers", "Recurring Work"),
    )
    assert "Weekly exterior windows" in recurring_list_body

    calendar_list_body = _assert_page_contract(
        client,
        "/admin/calendar?view=list",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers", "Recurring Work"),
    )
    assert f"Event #{appointment_id}" in calendar_list_body

    day_body = _assert_page_contract(
        client,
        f"/admin/calendar/{scheduled_date.year}/{scheduled_date.month:02d}/{scheduled_date.day:02d}",
        back_label="Back to Calendar View",
        expected_text=(f"Event #{appointment_id}",),
    )
    assert f"Recurring work #{recurring_work_id}" in day_body


def test_staff_assignment_workflow_end_to_end(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=True,
        ENABLE_CALENDAR=True,
        ENABLE_RECURRING_WORK=True,
        ENABLE_STAFF_MANAGEMENT=True,
    )
    context = _seed_workflow_context(app, include_appointment=True, include_recurring=False, include_staff=True)
    appointment_id = context["appointment_id"]
    staff_id = context["staff_id"]
    scheduled_date = context["scheduled_date"]

    _login_as_admin(client, admin_user)

    _assert_page_contract(
        client,
        "/admin/staff",
        main_nav=True,
        expected_nav_labels=("Requests", "Schedule", "Customers", "Staff", "Recurring Work"),
    )
    staff_detail_body = _assert_page_contract(
        client,
        f"/admin/staff/{staff_id}",
        back_label="Back to Staff",
        expected_text=("Services they can perform", "Weekly availability", "Scheduled hours"),
    )
    assert "No upcoming assigned scheduled work." in staff_detail_body

    appointment_detail_url = (
        f"/admin/appointments/{appointment_id}?source=day&date={scheduled_date.isoformat()}"
        f"&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}"
    )
    _assert_page_contract(
        client,
        appointment_detail_url,
        back_label="Back to Day Agenda",
        expected_text=("Staff assignment", "Can perform requested services", "Edit assignment"),
    )

    response = client.post(
        (
            f"/admin/appointments/{appointment_id}/assign-staff?source=day&date={scheduled_date.isoformat()}"
            f"&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}"
        ),
        data={
            "assign-staff-staff_ids": [str(staff_id)],
            "assign-staff-submit": "Save Staff Assignment",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Assigned now" in response.get_data(as_text=True)

    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assert appointment is not None
        assert [assignment.staff_member_id for assignment in appointment.staff_assignments] == [staff_id]

    updated_staff_body = _assert_page_contract(
        client,
        f"/admin/staff/{staff_id}",
        back_label="Back to Staff",
        expected_text=("Assigned scheduled work", "Window visit", "Scheduled hours this week"),
    )
    assert "2.0" in updated_staff_body


def test_workflow_pages_respect_feature_flags(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_CUSTOMER_RECORDS=False,
        ENABLE_CALENDAR=False,
        ENABLE_RECURRING_WORK=False,
        ENABLE_STAFF_MANAGEMENT=False,
    )

    _login_as_admin(client, admin_user)

    dashboard_body = _assert_page_contract(
        client,
        "/admin/",
        main_nav=True,
        expected_nav_labels=("Requests",),
    )
    assert "Customers" not in dashboard_body
    assert "Staff" not in dashboard_body
    assert "Recurring Work" not in dashboard_body

    assert client.get("/admin/customers").status_code == 302
    assert client.get("/admin/calendar").status_code == 302
    assert client.get("/admin/recurring-work").status_code == 302
    assert client.get("/admin/staff").status_code == 302

    app.config.update(ENABLE_SCHEDULING=False)
    assert client.get("/admin/scheduled-work/new").status_code == 302