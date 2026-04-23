from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import BadRequest, NotFound

from app.extensions import db
from app.models import APPOINTMENT_STATUSES, QUOTE_REQUEST_STATUSES, Appointment, QuoteRequest, RequestNote, User


def list_quote_requests() -> list[QuoteRequest]:
    statement = (
        select(QuoteRequest)
        .options(selectinload(QuoteRequest.services))
        .order_by(QuoteRequest.created_at.desc())
    )
    return list(db.session.scalars(statement))


def get_quote_request(request_id: int) -> QuoteRequest:
    statement = (
        select(QuoteRequest)
        .where(QuoteRequest.id == request_id)
        .options(
            selectinload(QuoteRequest.photos),
            selectinload(QuoteRequest.services),
            selectinload(QuoteRequest.notes).selectinload(RequestNote.author),
            selectinload(QuoteRequest.appointments),
        )
    )
    quote_request = db.session.scalar(statement)
    if quote_request is None:
        raise NotFound("Quote request not found.")
    return quote_request


def get_appointment(appointment_id: int) -> Appointment:
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        raise NotFound("Appointment not found.")
    return appointment


def create_appointment(
    request_id: int,
    requested_date,
    requested_time_window: str | None = None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    confirmed_date=None,
    confirmed_time_window: str | None = None,
    status: str = "Requested",
    previous_appointment_id: int | None = None,
) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")

    quote_request = get_quote_request(request_id)
    appointment = Appointment(
        requested_date=requested_date,
        requested_time_window=requested_time_window,
        confirmed_date=confirmed_date,
        confirmed_time_window=confirmed_time_window,
        customer_notes=customer_notes,
        internal_notes=internal_notes,
        status=status,
        previous_appointment_id=previous_appointment_id,
    )
    quote_request.appointments.append(appointment)
    db.session.commit()
    return appointment


def reschedule_appointment(
    appointment_id: int,
    requested_date,
    requested_time_window: str | None = None,
    internal_notes: str | None = None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    if appointment.status in ("Cancelled", "Completed", "No Show"):
        raise BadRequest("Cannot reschedule a closed appointment.")

    appointment.status = "Rescheduled"
    reschedule = Appointment(
        quote_request_id=appointment.quote_request_id,
        requested_date=requested_date,
        requested_time_window=requested_time_window,
        confirmed_date=None,
        confirmed_time_window=None,
        customer_notes=appointment.customer_notes,
        internal_notes=internal_notes or appointment.internal_notes,
        status="Requested",
        previous_appointment_id=appointment.id,
    )
    db.session.add(reschedule)
    db.session.commit()
    return reschedule


def update_appointment(
    appointment_id: int,
    requested_date,
    requested_time_window: str | None = None,
    confirmed_date=None,
    confirmed_time_window: str | None = None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    appointment.requested_date = requested_date
    appointment.requested_time_window = requested_time_window
    appointment.confirmed_date = confirmed_date
    appointment.confirmed_time_window = confirmed_time_window
    appointment.customer_notes = customer_notes
    appointment.internal_notes = internal_notes
    db.session.commit()
    return appointment


def update_appointment_status(appointment_id: int, status: str) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")

    appointment = get_appointment(appointment_id)
    appointment.status = status
    db.session.commit()
    return appointment


def update_request_status(request_id: int, status: str) -> QuoteRequest:
    if status not in QUOTE_REQUEST_STATUSES:
        raise BadRequest("Choose a valid status.")

    quote_request = get_quote_request(request_id)
    quote_request.status = status
    db.session.commit()
    return quote_request


def add_request_note(request_id: int, note_text: str, user: User) -> RequestNote:
    cleaned_note = note_text.strip()
    if not cleaned_note:
        raise BadRequest("Enter a note before saving.")

    quote_request = get_quote_request(request_id)
    note = RequestNote(note_text=cleaned_note, author=user)
    quote_request.notes.append(note)
    db.session.commit()
    return note