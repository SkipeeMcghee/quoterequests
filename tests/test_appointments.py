from __future__ import annotations

from datetime import date, time, timedelta

from app.extensions import db
from app.models import Appointment, Customer, QuoteRequest, RecurringWork, ServiceOption, StaffMember
from app.services.admin_requests import archive_recurring_work, create_appointment, create_scheduled_work, delete_appointment, generate_recurring_appointments_for_customer, reschedule_appointment, sync_recurring_work_appointments, update_appointment, update_appointment_status


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


def test_sync_recurring_work_appointments_updates_and_prunes_future_children(app):
    with app.app_context():
        app.config.update(ENABLE_SERVICES=True)
        customer = Customer(primary_name="Test User", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="weekly",
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=14)
        assert created_count > 0

        recurring_work.start_time = time(10, 0)
        recurring_work.end_time = time(12, 0)
        db.session.commit()

        sync_result = sync_recurring_work_appointments(recurring_work.id, days_ahead=14)
        assert sync_result.updated == created_count

        generated = db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).all()
        assert len(generated) == created_count
        assert all(appointment.start_time == time(10, 0) for appointment in generated)
        assert all(appointment.end_time == time(12, 0) for appointment in generated)
        assert all([service.name for service in appointment.services] == ["Window Cleaning"] for appointment in generated)

        recurring_work.status = "inactive"
        db.session.commit()

        delete_result = sync_recurring_work_appointments(recurring_work.id, days_ahead=14)
        assert delete_result.deleted == created_count
        assert db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).count() == 0


def test_recurring_exception_prevents_sync_from_removing_child_event(app):
    with app.app_context():
        app.config.update(ENABLE_SERVICES=True)
        customer = Customer(primary_name="Test User", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="weekly",
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        generate_recurring_appointments_for_customer(customer.id, days_ahead=14)
        protected_appointment = (
            db.session.query(Appointment)
            .filter_by(recurring_work_id=recurring_work.id)
            .order_by(Appointment.scheduled_date.asc(), Appointment.id.asc())
            .first()
        )
        protected_appointment.recurring_exception = True
        db.session.commit()

        recurring_work.day_of_week = (date.today().weekday() + 1) % 7
        db.session.commit()

        sync_result = sync_recurring_work_appointments(recurring_work.id, days_ahead=14)
        assert sync_result.deleted >= 1

        preserved = db.session.get(Appointment, protected_appointment.id)
        assert preserved is not None
        assert preserved.recurring_exception is True
        assert preserved.scheduled_date == protected_appointment.scheduled_date


def test_archive_recurring_work_removes_future_managed_children_but_keeps_exceptions(app):
    with app.app_context():
        app.config.update(ENABLE_SERVICES=True)
        customer = Customer(primary_name="Test User", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="weekly",
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=14)
        protected_appointment = (
            db.session.query(Appointment)
            .filter_by(recurring_work_id=recurring_work.id)
            .order_by(Appointment.scheduled_date.asc(), Appointment.id.asc())
            .first()
        )
        protected_appointment.recurring_exception = True
        db.session.commit()

        archive_result = archive_recurring_work(recurring_work.id)
        assert archive_result.deleted == created_count - 1
        assert recurring_work.status == "inactive"

        remaining = db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).all()
        assert len(remaining) == 1
        assert remaining[0].id == protected_appointment.id
        assert remaining[0].recurring_exception is True


def test_generate_biweekly_recurring_appointments_for_customer(app):
    with app.app_context():
        customer = Customer(primary_name="Biweekly Customer", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="biweekly",
            recurrence_config={"unit": "week", "interval": 2, "weekdays": [date.today().weekday()], "month_days": []},
            day_of_week=date.today().weekday(),
            starts_on=date.today(),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=30)
        generated_dates = [
            appointment.scheduled_date
            for appointment in db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).order_by(Appointment.scheduled_date.asc()).all()
        ]

        assert created_count == len(generated_dates)
        assert len(generated_dates) >= 2
        assert all((generated_dates[index] - generated_dates[index - 1]).days == 14 for index in range(1, len(generated_dates)))


def test_generate_semi_monthly_recurring_appointments_for_customer(app):
    with app.app_context():
        customer = Customer(primary_name="Semi Monthly Customer", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        today = date.today()
        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="semi_monthly",
            recurrence_config={"unit": "month", "interval": 1, "weekdays": [], "month_days": [1, 15]},
            day_of_month=1,
            starts_on=date(today.year, today.month, 1),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=40)
        generated_dates = [
            appointment.scheduled_date
            for appointment in db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).order_by(Appointment.scheduled_date.asc()).all()
        ]

        assert created_count == len(generated_dates)
        assert len(generated_dates) >= 2
        assert all(generated_date.day in {1, 15} for generated_date in generated_dates)


def test_generate_custom_twice_weekly_recurring_appointments(app):
    with app.app_context():
        customer = Customer(primary_name="Custom Weekly Customer", primary_email="test@example.com", primary_phone="555-1234", primary_city="Testville")
        db.session.add(customer)
        db.session.commit()

        first_weekday = date.today().weekday()
        second_weekday = (first_weekday + 2) % 7
        recurring_work = RecurringWork(
            customer_id=customer.id,
            title="Window Cleaning",
            frequency="custom",
            recurrence_config={"unit": "week", "interval": 1, "weekdays": [first_weekday, second_weekday], "month_days": []},
            day_of_week=first_weekday,
            starts_on=date.today(),
            status="active",
        )
        db.session.add(recurring_work)
        db.session.commit()

        created_count = generate_recurring_appointments_for_customer(customer.id, days_ahead=14)
        generated_dates = [
            appointment.scheduled_date
            for appointment in db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).order_by(Appointment.scheduled_date.asc()).all()
        ]

        assert created_count == len(generated_dates)
        assert len(generated_dates) >= 4
        assert {generated_date.weekday() for generated_date in generated_dates}.issubset({first_weekday, second_weekday})
        assert {first_weekday, second_weekday}.issubset({generated_date.weekday() for generated_date in generated_dates})


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
