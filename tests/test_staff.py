from __future__ import annotations

import json
from datetime import date, time, timedelta
from decimal import Decimal

from app.date_ranges import resolve_date_range_preset
from app.extensions import db
from app.models import (
    Appointment,
    AppointmentStaffAssignment,
    Customer,
    QuoteRequest,
    ServiceOption,
    StaffAvailability,
    StaffMember,
)


def _login_as_admin(client, admin_user):
    client.post(
        "/auth/login",
        data={"email": admin_user, "password": "password123", "remember_me": "y"},
        follow_redirects=False,
    )


def test_staff_list_surfaces_schedule_and_availability_context(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )
    scheduled_date = date.today() + timedelta(days=3)

    with app.app_context():
        service = ServiceOption(name="Window Cleaning")
        customer = Customer(primary_name="Jordan Client", primary_city="Test City")
        staff_member = StaffMember(
            display_name="Alex Crew",
            phone="555-111-2222",
            email="alex@example.com",
            role_title="Lead Tech",
            worker_type="employee",
            status="active",
            services=[service],
        )
        db.session.add_all([service, customer, staff_member])
        db.session.flush()

        db.session.add(
            StaffAvailability(
                staff_member_id=staff_member.id,
                day_of_week=scheduled_date.weekday(),
                start_time=time(8, 0),
                end_time=time(16, 0),
            )
        )

        appointment = Appointment(
            customer_id=customer.id,
            title="Exterior windows",
            scheduled_date=scheduled_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.flush()
        db.session.add(
            AppointmentStaffAssignment(
                appointment_id=appointment.id,
                staff_member_id=staff_member.id,
            )
        )
        appointment_id = appointment.id
        db.session.commit()

    _login_as_admin(client, admin_user)

    response = client.get("/admin/staff")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Scheduled hours are planning hours" in body
    assert "Alex Crew" in body
<<<<<<< HEAD
    assert f"Event #{appointment_id}" in body
=======
    assert "Lead Tech" not in body
    assert "Exterior windows" in body
>>>>>>> 7c44e41e837bd82372ab5a71aabd4bec807d88df
    assert "Open Day Agenda" in body
    assert "saved window" in body


def test_staff_detail_prioritizes_workflow_sections(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )
    upcoming_date = date.today() + timedelta(days=4)
    completed_date = date.today() - timedelta(days=1)

    with app.app_context():
        service_one = ServiceOption(name="Window Cleaning")
        service_two = ServiceOption(name="General Maintenance")
        customer = Customer(primary_name="Taylor Client", primary_city="Test City")
        staff_member = StaffMember(
            display_name="Morgan Field",
            phone="555-222-3333",
            email="morgan@example.com",
            role_title="Crew Lead",
            worker_type="contractor",
            status="active",
            compensation_amount=Decimal("27.50"),
            compensation_frequency="hourly",
            services=[service_one, service_two],
            notes="Prefers morning exterior work.",
        )
        db.session.add_all([service_one, service_two, customer, staff_member])
        db.session.flush()

        db.session.add_all(
            [
                StaffAvailability(
                    staff_member_id=staff_member.id,
                    day_of_week=upcoming_date.weekday(),
                    start_time=time(7, 30),
                    end_time=time(15, 0),
                ),
                StaffAvailability(
                    staff_member_id=staff_member.id,
                    day_of_week=completed_date.weekday(),
                    start_time=time(8, 0),
                    end_time=time(14, 0),
                    notes="Shorter shift.",
                ),
            ]
        )

        upcoming_appointment = Appointment(
            customer_id=customer.id,
            title="Seasonal cleanup",
            scheduled_date=upcoming_date,
            start_time=time(10, 0),
            end_time=time(12, 0),
            status="Scheduled",
        )
        completed_appointment = Appointment(
            customer_id=customer.id,
            title="Fence touch-up",
            scheduled_date=completed_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="Completed",
        )
        db.session.add_all([upcoming_appointment, completed_appointment])
        db.session.flush()
        db.session.add_all(
            [
                AppointmentStaffAssignment(
                    appointment_id=upcoming_appointment.id,
                    staff_member_id=staff_member.id,
                ),
                AppointmentStaffAssignment(
                    appointment_id=completed_appointment.id,
                    staff_member_id=staff_member.id,
                ),
            ]
        )
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)

    response = client.get(f"/admin/staff/{staff_member_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Staff Details" in body
    assert "Staff Notes" in body
    assert "Keep planning context, reminders, and field-specific details easy to update without leaving this record." not in body
    assert "Save Staff Notes" not in body
    assert body.count("Services they can perform") == 1
    assert "Used when matching scheduled work." in body
    assert "Planning view only." not in body
    assert "Crew Lead" not in body
    assert "Contractor" in body
    assert "Active" in body
    assert "555-222-3333" in body
    assert "morgan@example.com" in body
    assert "Staff Type" in body
    assert "Compensation" in body
    assert "Phone" in body
    assert "Email" in body
    assert "USD 27.50 / Hourly" in body
    assert body.index("morgan@example.com") < body.index("Scheduled Work") < body.index("Services they can perform")
    assert "staff-overview-grid__row" not in body
    assert body.count("Weekly availability") == 1
    assert "Hours Last Week" not in body
    assert "Hours This Week" not in body
    assert "Scheduled Hours by Date Range" in body
    assert "Filter scheduled hours" not in body
    assert "All Dates" in body
    assert "Preset" in body
    assert "Today" in body
    assert "Yesterday" in body
    assert "Tomorrow" in body
    assert "This Week to Date" in body
    assert "Last Month to Date" in body
    assert 'data-scheduled-hours-filter' in body
    assert 'data-scheduled-hours-preset' in body
    assert "Update Scheduled Hours" not in body
    assert "Total scheduled hours" not in body
    assert "Scheduled hours this week" not in body
    assert "Scheduled hours this month" not in body
    assert "Assigned scheduled work" in body
    assert "Recently completed scheduled work" in body
    assert "Add weekly availability" in body
    assert body.index("Add weekly availability") < body.index("Scheduled Hours by Date Range") < body.index("Assigned scheduled work")
    assert "Drag across a day to add availability." in body
    assert 'data-availability-board' in body
    assert 'data-availability-manual-days' in body
    assert "Clear all" in body
    assert "Window Cleaning" in body
    assert "General Maintenance" in body
    assert "View Schedule" in body

def test_staff_detail_defaults_scheduled_hours_filter_to_all_dates(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )

    with app.app_context():
        customer = Customer(primary_name="All Dates Client", primary_city="Test City")
        staff_member = StaffMember(
            display_name="All Dates Planner",
            worker_type="employee",
            status="active",
        )
        db.session.add_all([customer, staff_member])
        db.session.flush()

        appointment = Appointment(
            customer_id=customer.id,
            title="Any date work",
            scheduled_date=date.today(),
            start_time=time(9, 0),
            end_time=time(12, 0),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.flush()
        db.session.add(
            AppointmentStaffAssignment(
                appointment_id=appointment.id,
                staff_member_id=staff_member.id,
            )
        )
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)

    response = client.get(f"/admin/staff/{staff_member_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'value="all_dates" selected' in body
    assert ">3.0<" in body
    assert "All Dates" in body


def test_staff_notes_route_updates_notes(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )

    with app.app_context():
        staff_member = StaffMember(
            display_name="Jordan Notes",
            worker_type="employee",
            status="active",
            notes="Old note",
        )
        db.session.add(staff_member)
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)

    response = client.post(
        f"/admin/staff/{staff_member_id}/notes",
        data={
            "staff-notes-notes": "Updated planning note",
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"ok": True, "message": "Staff notes saved."}

    with app.app_context():
        staff_member = db.session.get(StaffMember, staff_member_id)
        assert staff_member.notes == "Updated planning note"


def test_new_staff_member_saves_compensation_pair(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        STAFF_COMPENSATION_CURRENCY="USD",
    )

    _login_as_admin(client, admin_user)

    response = client.post(
        "/admin/staff/new",
        data={
            "staff-display_name": "Casey Paid",
            "staff-phone": "555-444-1212",
            "staff-email": "casey@example.com",
            "staff-worker_type": "employee",
            "staff-status": "active",
            "staff-compensation_amount": "54000.00",
            "staff-compensation_frequency": "yearly",
            "staff-notes": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "USD 54000.00 / Yearly" in body

    with app.app_context():
        staff_member = StaffMember.query.filter_by(display_name="Casey Paid").one()
        assert staff_member.compensation_amount == Decimal("54000.00")
        assert staff_member.compensation_frequency == "yearly"


def test_staff_detail_applies_range_preset_filter(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )
    today = date.today()
    this_week_range = resolve_date_range_preset("this_week", reference_date=today)
    next_week_range = resolve_date_range_preset("next_week", reference_date=today)

    with app.app_context():
        customer = Customer(primary_name="Preset Client", primary_city="Test City")
        staff_member = StaffMember(
            display_name="Preset Planner",
            worker_type="employee",
            status="active",
        )
        db.session.add_all([customer, staff_member])
        db.session.flush()

        current_week_appointment = Appointment(
            customer_id=customer.id,
            title="Current week work",
            scheduled_date=this_week_range.start_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="Scheduled",
        )
        next_week_appointment = Appointment(
            customer_id=customer.id,
            title="Next week work",
            scheduled_date=next_week_range.start_date,
            start_time=time(10, 0),
            end_time=time(13, 0),
            status="Scheduled",
        )
        db.session.add_all([current_week_appointment, next_week_appointment])
        db.session.flush()
        db.session.add_all(
            [
                AppointmentStaffAssignment(
                    appointment_id=current_week_appointment.id,
                    staff_member_id=staff_member.id,
                ),
                AppointmentStaffAssignment(
                    appointment_id=next_week_appointment.id,
                    staff_member_id=staff_member.id,
                ),
            ]
        )
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)

    response = client.get(f"/admin/staff/{staff_member_id}?range_preset=next_week")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="range_preset"' in body
    assert 'value="next_week" selected' in body
    assert "Next Week" in body
    assert f'value="{next_week_range.start_date.isoformat()}"' in body
    assert f'value="{next_week_range.end_date.isoformat()}"' in body
    assert ">3.0<" in body


def test_staff_availability_route_accepts_monday_submission(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )

    with app.app_context():
        staff_member = StaffMember(
            display_name="Alex Monday",
            worker_type="employee",
            status="active",
        )
        db.session.add(staff_member)
        db.session.commit()
        staff_member_id = staff_member.id

    _login_as_admin(client, admin_user)

    response = client.post(
        f"/admin/staff/{staff_member_id}/availability",
        data={
            "availability-day_of_week": "0",
            "availability-start_time_hour": "8",
            "availability-start_time_minute": "0",
            "availability-end_time_hour": "16",
            "availability-end_time_minute": "0",
            "availability-notes": "Morning shift",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Availability added." in body

    with app.app_context():
        windows = StaffAvailability.query.filter_by(staff_member_id=staff_member_id).all()
        assert len(windows) == 1
        assert windows[0].day_of_week == 0
        assert windows[0].start_time == time(8, 0)
        assert windows[0].end_time == time(16, 0)
        assert windows[0].notes == "Morning shift"


def test_staff_availability_sync_route_replaces_week_windows(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )

    with app.app_context():
        staff_member = StaffMember(
            display_name="Morgan Planner",
            worker_type="employee",
            status="active",
        )
        db.session.add(staff_member)
        db.session.flush()

        existing_window = StaffAvailability(
            staff_member_id=staff_member.id,
            day_of_week=1,
            start_time=time(8, 0),
            end_time=time(12, 0),
            notes="Morning only",
        )
        db.session.add(existing_window)
        db.session.commit()
        staff_member_id = staff_member.id
        existing_window_id = existing_window.id

    _login_as_admin(client, admin_user)

    response = client.post(
        f"/admin/staff/{staff_member_id}/availability/sync",
        data={
            "availability-sync-windows_json": json.dumps(
                [
                    {
                        "id": existing_window_id,
                        "day_of_week": 1,
                        "start_time": "09:00",
                        "end_time": "13:00",
                        "notes": "Morning only",
                    },
                    {
                        "day_of_week": 4,
                        "start_time": "10:00",
                        "end_time": "15:00",
                        "notes": "",
                    },
                ]
            )
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["window_count"] == 2
    assert payload["day_count"] == 2

    with app.app_context():
        windows = StaffAvailability.query.filter_by(staff_member_id=staff_member_id).order_by(StaffAvailability.day_of_week, StaffAvailability.start_time).all()
        assert len(windows) == 2
        assert windows[0].id == existing_window_id
        assert windows[0].day_of_week == 1
        assert windows[0].start_time == time(9, 0)
        assert windows[0].end_time == time(13, 0)
        assert windows[0].notes == "Morning only"
        assert windows[1].day_of_week == 4
        assert windows[1].start_time == time(10, 0)
        assert windows[1].end_time == time(15, 0)

    clear_response = client.post(
        f"/admin/staff/{staff_member_id}/availability/sync",
        data={"availability-sync-windows_json": json.dumps([])},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert clear_response.status_code == 200
    clear_payload = clear_response.get_json()
    assert clear_payload["ok"] is True
    assert clear_payload["window_count"] == 0
    assert clear_payload["day_count"] == 0

    with app.app_context():
        windows = StaffAvailability.query.filter_by(staff_member_id=staff_member_id).all()
        assert windows == []


def test_appointment_detail_groups_assignment_choices_and_warnings(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )
    scheduled_date = date.today() + timedelta(days=2)

    with app.app_context():
        requested_service = ServiceOption(name="Window Cleaning")
        other_service = ServiceOption(name="Painting")
        customer = Customer(primary_name="Riley Client", primary_city="Test City")
        quote_request = QuoteRequest(
            full_name="Riley Client",
            phone="555-444-5555",
            city="Test City",
            customer=customer,
            services=[requested_service],
        )
        assigned_staff = StaffMember(
            display_name="Alex Match",
            role_title="Window Specialist",
            worker_type="employee",
            status="active",
            services=[requested_service],
        )
        conflicted_staff = StaffMember(
            display_name="Casey Conflict",
            role_title="Window Specialist",
            worker_type="employee",
            status="active",
            services=[requested_service],
        )
        fallback_staff = StaffMember(
            display_name="Morgan Backup",
            role_title="Painter",
            worker_type="contractor",
            status="active",
            services=[other_service],
        )
        db.session.add_all(
            [
                requested_service,
                other_service,
                customer,
                quote_request,
                assigned_staff,
                conflicted_staff,
                fallback_staff,
            ]
        )
        db.session.flush()

        db.session.add(
            StaffAvailability(
                staff_member_id=assigned_staff.id,
                day_of_week=scheduled_date.weekday(),
                start_time=time(8, 0),
                end_time=time(16, 0),
            )
        )

        appointment = Appointment(
            customer_id=customer.id,
            quote_request_id=quote_request.id,
            title="Window washing visit",
            scheduled_date=scheduled_date,
            start_time=time(10, 0),
            end_time=time(12, 0),
            status="Scheduled",
        )
        overlapping_appointment = Appointment(
            customer_id=customer.id,
            title="Overlap check",
            scheduled_date=scheduled_date,
            start_time=time(11, 0),
            end_time=time(13, 0),
            status="Scheduled",
        )
        db.session.add_all([appointment, overlapping_appointment])
        db.session.flush()
        db.session.add_all(
            [
                AppointmentStaffAssignment(
                    appointment_id=appointment.id,
                    staff_member_id=assigned_staff.id,
                ),
                AppointmentStaffAssignment(
                    appointment_id=overlapping_appointment.id,
                    staff_member_id=conflicted_staff.id,
                ),
            ]
        )
        db.session.commit()
        appointment_id = appointment.id

    _login_as_admin(client, admin_user)

    response = client.get(
        f"/admin/appointments/{appointment_id}?source=day&date={scheduled_date.isoformat()}&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}"
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Staff assignment" in body
    assert "Requested services" in body
    assert "Can perform requested services" in body
    assert "Other staff" in body
    assert "Can perform requested service" in body
    assert "No matching service listed" in body
    assert "Assigned now" in body
    assert "Weekly availability:" in body
    assert "Open Staff Record" in body
    assert "View Schedule" in body
    assert "No weekly availability is set for" in body
    assert "Already assigned to Event #" in body


def test_staff_assignment_post_accepts_checkbox_values(client, app, admin_user):
    app.config.update(
        ENABLE_SCHEDULING=True,
        ENABLE_STAFF_MANAGEMENT=True,
        ENABLE_CALENDAR=True,
    )
    scheduled_date = date.today() + timedelta(days=5)

    with app.app_context():
        service = ServiceOption(name="Window Cleaning")
        customer = Customer(primary_name="Jamie Client", primary_city="Test City")
        quote_request = QuoteRequest(
            full_name="Jamie Client",
            phone="555-777-8888",
            city="Test City",
            customer=customer,
            services=[service],
        )
        staff_one = StaffMember(display_name="Alex Assign", services=[service])
        staff_two = StaffMember(display_name="Morgan Assign", services=[service])
        appointment = Appointment(
            customer=customer,
            quote_request=quote_request,
            title="Assign window crew",
            scheduled_date=scheduled_date,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="Scheduled",
        )
        db.session.add_all([service, customer, quote_request, staff_one, staff_two, appointment])
        db.session.commit()
        appointment_id = appointment.id
        staff_one_id = staff_one.id
        staff_two_id = staff_two.id

    _login_as_admin(client, admin_user)

    response = client.post(
        f"/admin/appointments/{appointment_id}/assign-staff?source=day&date={scheduled_date.isoformat()}&year={scheduled_date.year}&month={scheduled_date.month}&day={scheduled_date.day}",
        data={
            "assign-staff-staff_ids": [str(staff_one_id), str(staff_two_id)],
            "assign-staff-submit": "Save Staff Assignment",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        appointment = db.session.get(Appointment, appointment_id)
        assigned_staff_ids = sorted(assignment.staff_member_id for assignment in appointment.staff_assignments)
        assert assigned_staff_ids == [staff_one_id, staff_two_id]

    body = response.get_data(as_text=True)
    assert "Alex Assign" in body
    assert "Morgan Assign" in body
    assert "Assigned now" in body