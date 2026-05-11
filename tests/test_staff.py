from __future__ import annotations

from datetime import date, time, timedelta

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
    assert f"Event #{appointment_id}" in body
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
    assert "Services they can perform" in body
    assert "Planning view only." in body
    assert "Scheduled hours this week" in body
    assert "Assigned scheduled work" in body
    assert "Recently completed scheduled work" in body
    assert "Add weekly availability" in body
    assert "Window Cleaning" in body
    assert "General Maintenance" in body
    assert "View Schedule" in body


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