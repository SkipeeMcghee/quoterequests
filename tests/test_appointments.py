from __future__ import annotations

from datetime import date, time, timedelta

from app.extensions import db
from app.models import Appointment, Customer, QuoteRequest, RecurringWork, ServiceOption, StaffMember
from app.services.admin_requests import create_appointment, create_scheduled_work, delete_appointment, generate_recurring_appointments_for_customer, reschedule_appointment, update_appointment, update_appointment_status


def _get_service(name: str) -> ServiceOption:
    return ServiceOption.query.filter_by(name=name).one()


def test_quote_request_can_have_zero_appointments(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        assert quote_request.appointments == []
        assert quote_request.current_appointment is None


def test_create_appointment_and_link_to_quote_request(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        requested_date = date.today() + timedelta(days=3)
        appointment = create_appointment(
            quote_request.id,
            requested_date,
            requested_time=time(9, 0),
            customer_notes="Preferred morning window.",
            internal_notes="Call before arrival.",
        )

        assert appointment.id is not None
        assert appointment.quote_request_id == quote_request.id
        assert appointment.status == "Requested"
        assert appointment.requested_date == requested_date
        assert appointment.requested_time == time(9, 0)
        assert appointment.customer_notes == "Preferred morning window."
        assert appointment.internal_notes == "Call before arrival."
        assert quote_request.current_appointment == appointment
        assert quote_request.appointments[0] == appointment


def test_reschedule_appointment_creates_new_linked_record(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        first_date = date.today() + timedelta(days=2)
        original = create_appointment(
            quote_request.id,
            first_date,
            requested_time=time(10, 0),
            customer_notes="Initial requested slot.",
            internal_notes="First appointment.",
        )

        second_date = first_date + timedelta(days=1)
        rescheduled = reschedule_appointment(
            original.id,
            requested_date=second_date,
            requested_time=time(11, 0),
            internal_notes="Rescheduled to next day.",
        )

        refreshed = db.session.get(QuoteRequest, quote_request.id)
        assert refreshed is not None
        assert refreshed.appointments[0].id == rescheduled.id
        assert refreshed.appointments[1].id == original.id
        assert original.status == "Rescheduled"
        assert rescheduled.previous_appointment_id == original.id
        assert rescheduled.status == "Requested"


def test_generate_recurring_appointments_for_customer(app):
    with app.app_context():
        customer = Customer(primary_name="Test User", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Weekly maintenance",
            frequency="weekly",
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=None,
            end_time=None,
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=30)
        assert created_count > 0

        second_run_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=30)
        assert second_run_count == 0

        generated = db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).all()
        assert len(generated) == created_count


def test_rescheduled_recurring_work_keeps_recurring_work_id(app):
    with app.app_context():
        customer = Customer(primary_name="Test User", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Weekly maintenance",
            frequency="weekly",
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=None,
            end_time=None,
        )
        db.session.add(recurring_work)
        db.session.commit()

        appointment = Appointment(
            customer_id=customer.id,
            recurring_work_id=recurring_work.id,
            title="Weekly maintenance",
            scheduled_date=date.today(),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.commit()

        rescheduled = reschedule_appointment(
            appointment.id,
            requested_date=date.today() + timedelta(days=7),
            requested_time=time(9, 0),
            internal_notes="Moved to next week.",
        )

        assert rescheduled.recurring_work_id == recurring_work.id
        assert rescheduled.previous_appointment_id == appointment.id


def test_update_appointment_status(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        appointment = create_appointment(
            quote_request.id,
            date.today() + timedelta(days=1),
            requested_time=time(13, 0),
        )

        updated = update_appointment_status(appointment.id, "Scheduled")
        assert updated.status == "Scheduled"
        assert db.session.get(Appointment, appointment.id).status == "Scheduled"


def test_update_appointment_marks_requested_work_scheduled_when_date_is_set(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        appointment = create_appointment(
            quote_request.id,
            date.today() + timedelta(days=1),
            requested_time=time(13, 0),
        )

        updated = update_appointment(
            appointment.id,
            title="On-site visit",
            scheduled_date=date.today() + timedelta(days=2),
            start_time=time(14, 0),
            end_time=time(15, 0),
        )

        assert updated.title == "On-site visit"
        assert updated.status == "Scheduled"
        assert db.session.get(Appointment, appointment.id).status == "Scheduled"


def test_create_scheduled_work_persists_selected_services_and_staff(app):
    app.config["ENABLE_SERVICES"] = True
    with app.app_context():
        service = _get_service("Window Cleaning")
        customer = Customer(primary_name="Test User", primary_city="Testville")
        staff_member = StaffMember(display_name="Alex Assign", worker_type="employee", status="active", services=[service])
        db.session.add_all([customer, staff_member])
        db.session.commit()

        appointment = create_scheduled_work(
            customer_id=customer.id,
            title="Window visit",
            scheduled_date=date.today() + timedelta(days=2),
            start_time=time(9, 0),
            end_time=time(10, 0),
            internal_notes="Bring ladder.",
            service_ids=[service.id],
            staff_ids=[staff_member.id],
        )

        assert appointment.title == "Window visit"
        assert [item.name for item in appointment.services] == ["Window Cleaning"]
        assert [assignment.staff_member_id for assignment in appointment.staff_assignments] == [staff_member.id]


def test_delete_appointment_updates_request_status(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        appointment = create_appointment(
            quote_request.id,
            date.today() + timedelta(days=1),
            title="On-site visit",
            scheduled_date=date.today() + timedelta(days=2),
            start_time=time(14, 0),
            end_time=time(15, 0),
        )

        assert appointment.title == "On-site visit"
        assert quote_request.status == "Scheduled"

        delete_appointment(appointment.id)

        refreshed_request = db.session.get(QuoteRequest, quote_request.id)
        assert refreshed_request is not None
        assert refreshed_request.current_appointment is None
        assert refreshed_request.status == "New"
