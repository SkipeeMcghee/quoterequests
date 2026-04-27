from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import BadRequest, NotFound

from app.extensions import db
from app.models import APPOINTMENT_STATUSES, QUOTE_REQUEST_STATUSES, Appointment, Customer, CustomerField, CustomerNote, QuoteRequest, RecurringWork, RequestNote, User


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
            selectinload(QuoteRequest.customer),
        )
    )
    quote_request = db.session.scalar(statement)
    if quote_request is None:
        raise NotFound("Quote request not found.")
    return quote_request


def list_customers() -> list[Customer]:
    statement = select(Customer).order_by(Customer.primary_name)
    return list(db.session.scalars(statement))


def get_customer(customer_id: int) -> Customer:
    statement = (
        select(Customer)
        .where(Customer.id == customer_id)
        .options(
            selectinload(Customer.fields),
            selectinload(Customer.notes),
            selectinload(Customer.quote_requests).selectinload(QuoteRequest.appointments),
            selectinload(Customer.recurring_works),
        )
    )
    customer = db.session.scalar(statement)
    if customer is None:
        raise NotFound("Customer not found.")
    return customer


def find_customer_matches_for_request(quote_request: QuoteRequest) -> list[Customer]:
    if quote_request.customer_id is not None:
        return []

    phone = (quote_request.phone or "").strip()
    email = (quote_request.email or "").strip().lower()
    if not phone and not email:
        return []

    statement = select(Customer).join(CustomerField, isouter=True)
    conditions = []
    if phone:
        conditions.append(
            (Customer.primary_phone == phone) |
            ((CustomerField.kind == "phone") & (CustomerField.value == phone))
        )
    if email:
        conditions.append(
            (Customer.primary_email == email) |
            ((CustomerField.kind == "email") & (CustomerField.value == email))
        )

    if not conditions:
        return []

    statement = statement.where(or_(*conditions)).distinct()
    return list(db.session.scalars(statement))


def create_customer_from_quote_request(request_id: int) -> Customer:
    quote_request = get_quote_request(request_id)
    if quote_request.customer_id is not None:
        raise BadRequest("Request is already linked to a customer.")

    primary_name = quote_request.full_name.strip() if quote_request.full_name else None
    primary_phone = (quote_request.phone or "").strip() or None
    primary_email = (quote_request.email or "").strip().lower() or None
    primary_city = quote_request.city.strip() if quote_request.city else None

    customer = Customer(
        primary_name=primary_name,
        primary_phone=primary_phone,
        primary_email=primary_email,
        primary_city=primary_city,
        billing_amount=None,
        billing_frequency=None,
    )
    db.session.add(customer)
    db.session.flush()

    if primary_name:
        db.session.add(CustomerField(customer_id=customer.id, kind="name", value=primary_name, is_primary=True, source_quote_request_id=quote_request.id))
    if primary_phone:
        db.session.add(CustomerField(customer_id=customer.id, kind="phone", value=primary_phone, is_primary=True, source_quote_request_id=quote_request.id))
    if primary_email:
        db.session.add(CustomerField(customer_id=customer.id, kind="email", value=primary_email, is_primary=True, source_quote_request_id=quote_request.id))
    if primary_city:
        db.session.add(CustomerField(customer_id=customer.id, kind="city", value=primary_city, is_primary=True, source_quote_request_id=quote_request.id))

    quote_request.customer = customer
    for appointment in quote_request.appointments:
        appointment.customer = customer

    db.session.commit()
    return customer


def link_quote_request_to_customer(request_id: int, customer_id: int) -> Customer:
    quote_request = get_quote_request(request_id)
    if quote_request.customer_id is not None:
        raise BadRequest("Request is already linked to a customer.")

    customer = db.session.get(Customer, customer_id)
    if customer is None:
        raise NotFound("Customer not found.")

    quote_request.customer = customer
    for appointment in quote_request.appointments:
        appointment.customer = customer

    db.session.commit()
    return customer


def merge_customers(source_customer_id: int, target_customer_id: int) -> Customer:
    if source_customer_id == target_customer_id:
        raise BadRequest("Source and target customer must be different.")

    source = get_customer(source_customer_id)
    target = get_customer(target_customer_id)

    if source.id == target.id:
        raise BadRequest("Source and target customer must be different.")

    if source.primary_name and not target.primary_name:
        target.primary_name = source.primary_name
    if source.primary_phone and not target.primary_phone:
        target.primary_phone = source.primary_phone
    if source.primary_email and not target.primary_email:
        target.primary_email = source.primary_email
    if source.primary_city and not target.primary_city:
        target.primary_city = source.primary_city

    target_field_keys = {(field.kind, field.value) for field in target.fields}
    target_primary_by_kind = {field.kind: field for field in target.fields if field.is_primary}

    for field in list(source.fields):
        key = (field.kind, field.value)
        if key in target_field_keys:
            if field.is_primary and field.kind not in target_primary_by_kind:
                matching = next((f for f in target.fields if f.kind == field.kind and f.value == field.value), None)
                if matching:
                    matching.is_primary = True
            db.session.delete(field)
            continue

        if field.is_primary and field.kind in target_primary_by_kind:
            field.is_primary = False
        field.customer_id = target.id
        target_field_keys.add(key)
        if field.is_primary:
            target_primary_by_kind[field.kind] = field

    for note in source.notes:
        note.customer_id = target.id

    for quote_request in source.quote_requests:
        quote_request.customer_id = target.id

    db.session.delete(source)
    db.session.commit()
    return target


def add_customer_field(customer_id: int, kind: str, value: str) -> CustomerField:
    cleaned_value = (value or "").strip()
    if not cleaned_value:
        raise BadRequest("Enter a value before saving.")
    if kind not in ("name", "phone", "email", "city"):
        raise BadRequest("Invalid customer field type.")

    customer = get_customer(customer_id)
    existing = (
        db.session.query(CustomerField)
        .filter_by(customer_id=customer_id, kind=kind, value=cleaned_value)
        .one_or_none()
    )
    if existing is not None:
        raise BadRequest("This value already exists for the customer.")

    is_primary = not any(field.is_primary for field in customer.fields if field.kind == kind)
    field = CustomerField(
        customer_id=customer_id,
        kind=kind,
        value=cleaned_value,
        is_primary=is_primary,
    )
    db.session.add(field)

    if is_primary:
        if kind == "name":
            customer.primary_name = cleaned_value
        elif kind == "phone":
            customer.primary_phone = cleaned_value
        elif kind == "email":
            customer.primary_email = cleaned_value
        elif kind == "city":
            customer.primary_city = cleaned_value

    db.session.commit()
    return field


def set_primary_customer_field(customer_id: int, field_id: int) -> CustomerField:
    customer = get_customer(customer_id)
    field = db.session.get(CustomerField, field_id)
    if field is None or field.customer_id != customer_id:
        raise NotFound("Customer field not found.")

    for existing in customer.fields:
        if existing.kind == field.kind:
            existing.is_primary = (existing.id == field_id)

    if field.kind == "name":
        customer.primary_name = field.value
    elif field.kind == "phone":
        customer.primary_phone = field.value
    elif field.kind == "email":
        customer.primary_email = field.value
    elif field.kind == "city":
        customer.primary_city = field.value

    db.session.commit()
    return field


def update_customer_billing(customer_id: int, billing_amount, billing_frequency: str | None) -> Customer:
    customer = get_customer(customer_id)
    if billing_amount is not None and billing_amount != "":
        try:
            billing_amount = Decimal(str(billing_amount))
        except (InvalidOperation, ValueError):
            raise BadRequest("Enter a valid billing amount.")
        if billing_amount < 0:
            raise BadRequest("Billing amount cannot be negative.")
        customer.billing_amount = billing_amount
    else:
        customer.billing_amount = None

    if billing_frequency:
        if billing_frequency not in Customer.BILLING_FREQUENCIES:
            raise BadRequest("Choose a valid billing frequency.")
        customer.billing_frequency = billing_frequency
    else:
        customer.billing_frequency = None

    db.session.commit()
    return customer


def add_customer_note(customer_id: int, note_text: str, user: User) -> CustomerNote:
    cleaned_note = note_text.strip()
    if not cleaned_note:
        raise BadRequest("Enter a note before saving.")

    customer = get_customer(customer_id)
    note = CustomerNote(customer_id=customer.id, note_text=cleaned_note, created_by=user.id)
    db.session.add(note)
    db.session.commit()
    return note


def get_appointment(appointment_id: int) -> Appointment:
    statement = (
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .options(
            selectinload(Appointment.quote_request),
            selectinload(Appointment.customer),
            selectinload(Appointment.recurring_work),
            selectinload(Appointment.previous_appointment),
            selectinload(Appointment.rescheduled_appointments),
        )
    )
    appointment = db.session.scalar(statement)
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
    title: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str = "Requested",
    previous_appointment_id: int | None = None,
) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")

    quote_request = get_quote_request(request_id)
    appointment = Appointment(
        customer_id=quote_request.customer_id,
        quote_request_id=quote_request.id,
        title=title,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
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
    scheduled_date=None,
    start_time=None,
    end_time=None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    if appointment.status in ("Cancelled", "Completed", "No Show"):
        raise BadRequest("Cannot reschedule a closed appointment.")

    appointment.status = "Rescheduled"
    reschedule = Appointment(
        customer_id=appointment.customer_id,
        quote_request_id=appointment.quote_request_id,
        recurring_work_id=appointment.recurring_work_id,
        title=appointment.title,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
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
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str | None = None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    appointment.requested_date = requested_date
    appointment.requested_time_window = requested_time_window
    appointment.confirmed_date = confirmed_date
    appointment.confirmed_time_window = confirmed_time_window
    appointment.customer_notes = customer_notes
    appointment.internal_notes = internal_notes
    appointment.scheduled_date = scheduled_date
    appointment.start_time = start_time
    appointment.end_time = end_time
    if status is not None:
        if status not in APPOINTMENT_STATUSES:
            raise BadRequest("Choose a valid appointment status.")
        appointment.status = status
    db.session.commit()
    return appointment


def update_appointment_status(appointment_id: int, status: str) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")

    appointment = get_appointment(appointment_id)
    appointment.status = status
    db.session.commit()
    return appointment


def list_recurring_works() -> list[RecurringWork]:
    statement = (
        select(RecurringWork)
        .options(
            selectinload(RecurringWork.customer),
            selectinload(RecurringWork.appointments),
        )
        .order_by(RecurringWork.starts_on.desc())
    )
    return list(db.session.scalars(statement))


def get_recurring_work(recurring_work_id: int) -> RecurringWork:
    statement = (
        select(RecurringWork)
        .where(RecurringWork.id == recurring_work_id)
        .options(
            selectinload(RecurringWork.customer),
            selectinload(RecurringWork.appointments),
        )
    )
    recurring_work = db.session.scalar(statement)
    if recurring_work is None:
        raise NotFound("Recurring work not found.")
    return recurring_work


def generate_appointments_for_recurring_work(recurring_work_id: int, days_ahead: int = 60) -> int:
    recurring_work = get_recurring_work(recurring_work_id)
    if recurring_work.status != "active":
        return 0

    start_date = max(date.today(), recurring_work.starts_on)
    window_end = date.today() + timedelta(days=days_ahead)
    if recurring_work.ends_on is not None:
        window_end = min(window_end, recurring_work.ends_on)

    appointments_for_work = db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).all()
    existing_dates = {
        appointment.scheduled_date
        for appointment in appointments_for_work
        if appointment.scheduled_date is not None
    }

    new_appointments = []

    def add_candidate(candidate_date: date) -> None:
        if candidate_date < recurring_work.starts_on or candidate_date > window_end:
            return
        if candidate_date in existing_dates:
            return
        appointment = Appointment(
            customer_id=recurring_work.customer_id,
            quote_request_id=recurring_work.quote_request_id,
            recurring_work_id=recurring_work.id,
            title=recurring_work.title or "Recurring work",
            scheduled_date=candidate_date,
            start_time=recurring_work.start_time,
            end_time=recurring_work.end_time,
            status="Scheduled",
            internal_notes=f"Generated from recurring work #{recurring_work.id}",
        )
        db.session.add(appointment)
        new_appointments.append(appointment)

    if recurring_work.frequency == "weekly":
        if recurring_work.day_of_week is None:
            raise BadRequest("Weekly recurring work requires a day of week.")
        offset = (recurring_work.day_of_week - start_date.weekday()) % 7
        candidate = start_date + timedelta(days=offset)
        while candidate <= window_end:
            add_candidate(candidate)
            candidate += timedelta(days=7)
    elif recurring_work.frequency == "monthly":
        if recurring_work.day_of_month is None:
            raise BadRequest("Monthly recurring work requires a day of month.")

        def days_in_month(year: int, month: int) -> int:
            if month == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month + 1, 1)
            return (next_month - date(year, month, 1)).days

        candidate_year = start_date.year
        candidate_month = start_date.month
        candidate_day = recurring_work.day_of_month

        while True:
            if candidate_day <= days_in_month(candidate_year, candidate_month):
                candidate = date(candidate_year, candidate_month, candidate_day)
                if candidate >= start_date:
                    add_candidate(candidate)
            if candidate_year > window_end.year or (candidate_year == window_end.year and candidate_month >= window_end.month):
                break
            if candidate_month == 12:
                candidate_month = 1
                candidate_year += 1
            else:
                candidate_month += 1
    else:
        raise BadRequest("Recurring work must be weekly or monthly.")

    if new_appointments:
        db.session.commit()

    return len(new_appointments)


def generate_recurring_appointments_for_customer(customer_id: int, days_ahead: int = 60) -> int:
    customer = get_customer(customer_id)
    total_created = 0
    for recurring_work in customer.recurring_works:
        total_created += generate_appointments_for_recurring_work(recurring_work.id, days_ahead=days_ahead)
    return total_created


def list_scheduled_appointments(start_date: date, end_date: date) -> list[Appointment]:
    statement = (
        select(Appointment)
        .where(
            Appointment.scheduled_date >= start_date,
            Appointment.scheduled_date <= end_date,
            Appointment.status != "Cancelled",
        )
        .options(
            selectinload(Appointment.quote_request),
            selectinload(Appointment.customer),
        )
        .order_by(Appointment.scheduled_date, Appointment.start_time, Appointment.id)
    )
    return list(db.session.scalars(statement))


def list_appointments_for_month(year: int, month: int) -> list[Appointment]:
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    return list_scheduled_appointments(first_day, last_day)


def list_appointments_for_day(year: int, month: int, day: int) -> list[Appointment]:
    view_date = date(year, month, day)
    return list_scheduled_appointments(view_date, view_date)


def update_last_contacted_on(request_id: int, last_contacted_on) -> QuoteRequest:
    quote_request = get_quote_request(request_id)
    quote_request.last_contacted_on = last_contacted_on
    db.session.commit()
    return quote_request


def update_request_status(request_id: int, status: str) -> QuoteRequest:
    if status not in QUOTE_REQUEST_STATUSES:
        raise BadRequest("Choose a valid status.")

    quote_request = get_quote_request(request_id)
    quote_request.status = status
    quote_request.last_contacted_on = date.today()
    db.session.commit()
    return quote_request


def get_request_note(note_id: int) -> RequestNote:
    note = db.session.get(RequestNote, note_id)
    if note is None:
        raise NotFound("Note not found.")
    return note


def add_request_note(request_id: int, note_text: str, user: User) -> RequestNote:
    cleaned_note = note_text.strip()
    if not cleaned_note:
        raise BadRequest("Enter a note before saving.")

    quote_request = get_quote_request(request_id)
    note = RequestNote(note_text=cleaned_note, author=user)
    quote_request.notes.append(note)
    db.session.commit()
    return note


def update_request_note(note_id: int, note_text: str) -> RequestNote:
    note = get_request_note(note_id)
    cleaned_note = note_text.strip()
    if not cleaned_note:
        raise BadRequest("Enter a note before saving.")

    note.note_text = cleaned_note
    db.session.commit()
    return note


def delete_request_note(note_id: int) -> None:
    note = get_request_note(note_id)
    db.session.delete(note)
    db.session.commit()
