from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.models import Appointment, QuoteRequest
from app.services.admin_requests import create_appointment, reschedule_appointment, update_appointment_status


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
            requested_time_window="9am - 12pm",
            customer_notes="Preferred morning window.",
            internal_notes="Call before arrival.",
        )

        assert appointment.id is not None
        assert appointment.quote_request_id == quote_request.id
        assert appointment.status == "Requested"
        assert appointment.requested_date == requested_date
        assert appointment.requested_time_window == "9am - 12pm"
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
            requested_time_window="10am - 12pm",
            customer_notes="Initial requested slot.",
            internal_notes="First appointment.",
        )

        second_date = first_date + timedelta(days=1)
        rescheduled = reschedule_appointment(
            original.id,
            requested_date=second_date,
            requested_time_window="11am - 1pm",
            internal_notes="Rescheduled to next day.",
        )

        refreshed = db.session.get(QuoteRequest, quote_request.id)
        assert refreshed is not None
        assert refreshed.appointments[0].id == rescheduled.id
        assert refreshed.appointments[1].id == original.id
        assert original.status == "Rescheduled"
        assert rescheduled.previous_appointment_id == original.id
        assert rescheduled.status == "Requested"


def test_update_appointment_status(app):
    with app.app_context():
        quote_request = QuoteRequest(full_name="Test User", phone="555-1234", email="test@example.com", city="Testville")
        db.session.add(quote_request)
        db.session.commit()

        appointment = create_appointment(
            quote_request.id,
            date.today() + timedelta(days=1),
            requested_time_window="1pm - 3pm",
        )

        updated = update_appointment_status(appointment.id, "Confirmed")
        assert updated.status == "Confirmed"
        assert db.session.get(Appointment, appointment.id).status == "Confirmed"
