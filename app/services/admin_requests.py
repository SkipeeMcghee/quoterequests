from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import BadRequest, NotFound

from app.extensions import db
from app.models import (
    APPOINTMENT_STATUSES,
    QUOTE_REQUEST_STATUSES,
    Appointment,
    AppointmentStaffAssignment,
    Customer,
    CustomerAddress,
    CustomerField,
    CustomerNote,
    CustomerPhoto,
    QuoteRequest,
    RecurringWork,
    RequestNote,
    RequestQuote,
    ServiceOption,
    StaffAvailability,
    StaffMember,
    User,
)
from app.services.uploads import save_customer_photos


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
            selectinload(QuoteRequest.quotes),
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
            selectinload(Customer.addresses),
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


def create_customer(
    primary_name: str,
    primary_phone: str | None = None,
    primary_email: str | None = None,
    primary_city: str | None = None,
) -> Customer:
    cleaned_name = (primary_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Customer name cannot be blank.")
    cleaned_city = (primary_city or "").strip()
    if not cleaned_city:
        raise BadRequest("Customer city cannot be blank.")

    customer = Customer(
        primary_name=cleaned_name,
        primary_phone=(primary_phone or "").strip() or None,
        primary_email=(primary_email or "").strip().lower() or None,
        primary_city=cleaned_city,
        billing_amount=None,
        billing_frequency=None,
    )
    db.session.add(customer)
    db.session.flush()

    if customer.primary_name:
        db.session.add(CustomerField(customer_id=customer.id, kind="name", value=customer.primary_name, is_primary=True))
    if customer.primary_phone:
        db.session.add(CustomerField(customer_id=customer.id, kind="phone", value=customer.primary_phone, is_primary=True))
    if customer.primary_email:
        db.session.add(CustomerField(customer_id=customer.id, kind="email", value=customer.primary_email, is_primary=True))
    if customer.primary_city:
        db.session.add(CustomerField(customer_id=customer.id, kind="city", value=customer.primary_city, is_primary=True))

    db.session.commit()
    return customer


def list_staff_members() -> list[StaffMember]:
    statement = (
        select(StaffMember)
        .options(
            selectinload(StaffMember.services),
            selectinload(StaffMember.availability_windows),
            selectinload(StaffMember.assigned_appointments).selectinload(Appointment.customer),
            selectinload(StaffMember.assigned_appointments).selectinload(Appointment.quote_request),
        )
        .order_by(StaffMember.display_name)
    )
    return list(db.session.scalars(statement))


def get_staff_member(staff_member_id: int) -> StaffMember:
    statement = (
        select(StaffMember)
        .where(StaffMember.id == staff_member_id)
        .options(
            selectinload(StaffMember.services),
            selectinload(StaffMember.availability_windows),
            selectinload(StaffMember.assigned_appointments).selectinload(Appointment.customer),
            selectinload(StaffMember.assigned_appointments).selectinload(Appointment.quote_request),
        )
    )
    staff_member = db.session.scalar(statement)
    if staff_member is None:
        raise NotFound("Staff member not found.")
    return staff_member


def create_staff_member(
    display_name: str,
    phone: str | None = None,
    email: str | None = None,
    role_title: str | None = None,
    worker_type: str = "employee",
    status: str = "active",
    notes: str | None = None,
    service_ids: list[int] | None = None,
) -> StaffMember:
    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Staff member name cannot be blank.")

    staff_member = StaffMember(
        display_name=cleaned_name,
        phone=(phone or "").strip() or None,
        email=(email or "").strip().lower() or None,
        role_title=(role_title or "").strip() or None,
        worker_type=worker_type,
        status=status,
        notes=(notes or "").strip() or None,
    )
    if service_ids:
        staff_member.services = list(
            ServiceOption.query.filter(ServiceOption.id.in_(service_ids)).order_by(ServiceOption.name).all()
        )
    db.session.add(staff_member)
    db.session.commit()
    return staff_member


def update_staff_member(
    staff_member_id: int,
    display_name: str,
    phone: str | None = None,
    email: str | None = None,
    role_title: str | None = None,
    worker_type: str = "employee",
    status: str = "active",
    notes: str | None = None,
    service_ids: list[int] | None = None,
) -> StaffMember:
    staff_member = db.session.get(StaffMember, staff_member_id)
    if staff_member is None:
        raise NotFound("Staff member not found.")

    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Staff member name cannot be blank.")

    staff_member.display_name = cleaned_name
    staff_member.phone = (phone or "").strip() or None
    staff_member.email = (email or "").strip().lower() or None
    staff_member.role_title = (role_title or "").strip() or None
    staff_member.worker_type = worker_type
    staff_member.status = status
    staff_member.notes = (notes or "").strip() or None
    if service_ids is not None:
        staff_member.services = list(
            ServiceOption.query.filter(ServiceOption.id.in_(service_ids)).order_by(ServiceOption.name).all()
        )
    db.session.commit()
    return staff_member


def set_appointment_staff_assignments(appointment_id: int, staff_ids: list[int] | None) -> Appointment:
    appointment = get_appointment(appointment_id)
    current_staff_ids = {assignment.staff_member_id for assignment in appointment.staff_assignments}
    desired_staff_ids = set(staff_ids or [])

    for assignment in list(appointment.staff_assignments):
        if assignment.staff_member_id not in desired_staff_ids:
            db.session.delete(assignment)

    for staff_id in desired_staff_ids - current_staff_ids:
        staff_member = db.session.get(StaffMember, staff_id)
        if staff_member is None:
            raise NotFound("Staff member not found.")
        appointment.staff_assignments.append(AppointmentStaffAssignment(staff_member_id=staff_id))

    db.session.commit()
    return appointment


def find_staff_for_service_options(service_option_ids: list[int]) -> list[StaffMember]:
    if not service_option_ids:
        return list_staff_members()

    statement = (
        select(StaffMember)
        .join(StaffMember.services)
        .where(ServiceOption.id.in_(service_option_ids))
        .options(selectinload(StaffMember.services))
        .order_by(StaffMember.display_name)
        .distinct()
    )
    return list(db.session.scalars(statement))


def get_staff_assignment_warnings(appointment: Appointment, staff_member: StaffMember) -> list[str]:
    warnings: list[str] = []
    if appointment.scheduled_date is None or appointment.start_time is None or appointment.end_time is None:
        return warnings

    weekday = appointment.scheduled_date.weekday()
    available_windows = [
        window
        for window in staff_member.availability_windows
        if window.day_of_week == weekday
    ]
    if not available_windows:
        warnings.append(f"No weekly availability is set for {appointment.scheduled_date.strftime('%A')}.")
    else:
        within_window = any(
            window.start_time <= appointment.start_time and window.end_time >= appointment.end_time
            for window in available_windows
        )
        if not within_window:
            warnings.append(
                f"Scheduled outside the saved availability window on {appointment.scheduled_date.strftime('%A')} ({appointment.start_time.strftime('%H:%M')}–{appointment.end_time.strftime('%H:%M')})."
            )

    for other in staff_member.assigned_appointments:
        if other.id == appointment.id or other.scheduled_date is None or other.start_time is None or other.end_time is None:
            continue
        if other.status == "Cancelled":
            continue
        if other.scheduled_date != appointment.scheduled_date:
            continue

        start_a = appointment.start_time
        end_a = appointment.end_time
        start_b = other.start_time
        end_b = other.end_time
        if start_a < end_b and start_b < end_a:
            warnings.append(
                f"Already assigned to Event #{other.id} on {other.scheduled_date.strftime('%b %d')} during an overlapping time."
            )
            break

    return warnings


def add_staff_availability(
    staff_member_id: int,
    day_of_week: int,
    start_time,
    end_time,
    notes: str | None = None,
) -> StaffAvailability:
    staff_member = db.session.get(StaffMember, staff_member_id)
    if staff_member is None:
        raise NotFound("Staff member not found.")
    if day_of_week < 0 or day_of_week > 6:
        raise BadRequest("Day of week must be between 0 and 6.")
    if start_time is None or end_time is None:
        raise BadRequest("Start and end times are required.")
    if end_time <= start_time:
        raise BadRequest("End time must be after start time.")

    availability = StaffAvailability(
        staff_member_id=staff_member_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        notes=(notes or "").strip() or None,
    )
    db.session.add(availability)
    db.session.commit()
    return availability


def delete_staff_availability(staff_availability_id: int) -> None:
    availability = db.session.get(StaffAvailability, staff_availability_id)
    if availability is None:
        raise NotFound("Staff availability not found.")
    db.session.delete(availability)
    db.session.commit()


def create_scheduled_work(
    request_id: int | None = None,
    customer_id: int | None = None,
    new_customer_name: str | None = None,
    new_customer_phone: str | None = None,
    new_customer_email: str | None = None,
    new_customer_city: str | None = None,
    title: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str = "Scheduled",
    customer_notes: str | None = None,
    internal_notes: str | None = None,
) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")
    if start_time is None or end_time is None:
        raise BadRequest("Start and end times are required.")
    if end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

    quote_request = None
    if request_id is not None:
        quote_request = get_quote_request(request_id)

    customer = None
    if customer_id is not None:
        customer = db.session.get(Customer, customer_id)
        if customer is None:
            raise NotFound("Customer not found.")
    elif quote_request is not None and quote_request.customer is not None:
        customer = quote_request.customer
    elif new_customer_name or new_customer_city:
        customer = create_customer(
            primary_name=new_customer_name or "",
            primary_phone=new_customer_phone,
            primary_email=new_customer_email,
            primary_city=new_customer_city,
        )
    else:
        raise BadRequest("Select an existing customer or enter a new customer name and city.")

    if quote_request is not None and quote_request.customer is None:
        quote_request.customer = customer

    appointment = Appointment(
        customer_id=customer.id,
        quote_request_id=quote_request.id if quote_request is not None else None,
        title=(title or "").strip() or None,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        status=status,
        customer_notes=(customer_notes or "").strip() or None,
        internal_notes=(internal_notes or "").strip() or None,
    )
    db.session.add(appointment)
    if quote_request is not None:
        quote_request.appointments.append(appointment)
        quote_request.sync_status()

    db.session.commit()
    return appointment


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

    for address in source.addresses:
        address.customer_id = target.id

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


def add_customer_address(
    customer_id: int,
    address_line_1: str | None = None,
    address_line_2: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    is_billing: bool = False,
) -> CustomerAddress:
    customer = get_customer(customer_id)
    cleaned_line_1 = (address_line_1 or "").strip() or None
    cleaned_line_2 = (address_line_2 or "").strip() or None
    cleaned_state = (state or "").strip() or None
    cleaned_zip = (zip_code or "").strip() or None
    if not (cleaned_line_1 or cleaned_line_2 or cleaned_state or cleaned_zip):
        raise BadRequest("Enter at least one address field before saving.")

    if is_billing:
        for existing in customer.addresses:
            existing.is_billing = False

    address = CustomerAddress(
        customer_id=customer_id,
        address_line_1=cleaned_line_1,
        address_line_2=cleaned_line_2,
        state=cleaned_state,
        zip_code=cleaned_zip,
        is_billing=is_billing,
    )
    db.session.add(address)
    db.session.flush()

    if not is_billing and len(customer.addresses) == 0:
        address.is_billing = True

    db.session.commit()
    return address


def set_customer_billing_address(customer_id: int, address_id: int) -> CustomerAddress:
    customer = get_customer(customer_id)
    address = db.session.get(CustomerAddress, address_id)
    if address is None or address.customer_id != customer_id:
        raise NotFound("Customer address not found.")

    for existing in customer.addresses:
        existing.is_billing = (existing.id == address_id)

    db.session.commit()
    return address


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


def update_customer_info(customer_id: int, primary_name: str, primary_phone: str | None, primary_email: str | None, primary_city: str | None) -> Customer:
    customer = get_customer(customer_id)
    cleaned_name = (primary_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Customer name cannot be blank.")
    cleaned_city = (primary_city or "").strip()
    if not cleaned_city:
        raise BadRequest("Customer city cannot be blank.")

    customer.primary_name = cleaned_name
    customer.primary_phone = (primary_phone or "").strip() or None
    customer.primary_email = (primary_email or "").strip().lower() or None
    customer.primary_city = cleaned_city
    db.session.commit()
    return customer


def upload_customer_photos(customer_id: int, uploaded_files: list) -> list[CustomerPhoto]:
    customer = get_customer(customer_id)
    photos = save_customer_photos(uploaded_files, customer_id)
    for photo in photos:
        photo.customer = customer
        db.session.add(photo)
    db.session.commit()
    return photos


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
            selectinload(Appointment.staff_assignments).selectinload(AppointmentStaffAssignment.staff_member),
        )
    )
    appointment = db.session.scalar(statement)
    if appointment is None:
        raise NotFound("Appointment not found.")
    return appointment


def create_appointment(
    request_id: int,
    requested_date,
    requested_time=None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    confirmed_date=None,
    confirmed_time=None,
    title: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str = "Requested",
    previous_appointment_id: int | None = None,
) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

    quote_request = get_quote_request(request_id)
    appointment = Appointment(
        customer_id=quote_request.customer_id,
        quote_request_id=quote_request.id,
        title=title,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        requested_date=requested_date,
        requested_time=requested_time,
        confirmed_date=confirmed_date,
        confirmed_time=confirmed_time,
        customer_notes=customer_notes,
        internal_notes=internal_notes,
        status=status,
        previous_appointment_id=previous_appointment_id,
    )
    quote_request.appointments.append(appointment)
    quote_request.sync_status()
    db.session.commit()
    return appointment


def reschedule_appointment(
    appointment_id: int,
    requested_date,
    requested_time=None,
    internal_notes: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    if appointment.status in ("Cancelled", "Completed", "No Show"):
        raise BadRequest("Cannot reschedule a closed appointment.")
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

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
        requested_time=requested_time,
        confirmed_date=None,
        confirmed_time=None,
        customer_notes=appointment.customer_notes,
        internal_notes=internal_notes or appointment.internal_notes,
        status="Requested",
        previous_appointment_id=appointment.id,
    )
    db.session.add(reschedule)
    if appointment.quote_request is not None:
        appointment.quote_request.sync_status()
    db.session.commit()
    return reschedule


def update_appointment(
    appointment_id: int,
    requested_date=None,
    title: str | None = None,
    requested_time=None,
    confirmed_date=None,
    confirmed_time=None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str | None = None,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

    appointment.title = title
    appointment.requested_date = requested_date
    appointment.requested_time = requested_time
    appointment.confirmed_date = confirmed_date
    appointment.confirmed_time = confirmed_time
    appointment.customer_notes = customer_notes
    appointment.internal_notes = internal_notes
    appointment.scheduled_date = scheduled_date
    appointment.start_time = start_time
    appointment.end_time = end_time
    if status is not None:
        if status not in APPOINTMENT_STATUSES:
            raise BadRequest("Choose a valid appointment status.")
        appointment.status = status
    if appointment.quote_request is not None:
        appointment.quote_request.sync_status()
    db.session.commit()
    return appointment


def update_appointment_status(appointment_id: int, status: str) -> Appointment:
    if status not in APPOINTMENT_STATUSES:
        raise BadRequest("Choose a valid appointment status.")

    appointment = get_appointment(appointment_id)
    appointment.status = status
    if appointment.quote_request is not None:
        appointment.quote_request.sync_status()
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


def _normalize_recurring_work_values(
    *,
    title: str,
    frequency: str,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    status: str = "active",
    notes: str | None = None,
) -> dict[str, object]:
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise BadRequest("Enter a service or work title.")

    if frequency not in RecurringWork.FREQUENCIES:
        raise BadRequest("Choose a valid recurring frequency.")

    cleaned_day_of_week = day_of_week
    cleaned_day_of_month = day_of_month
    if frequency == "weekly":
        if cleaned_day_of_week is None or cleaned_day_of_week < 0 or cleaned_day_of_week > 6:
            raise BadRequest("Choose a weekday for weekly recurring work.")
        cleaned_day_of_month = None
    if frequency == "monthly":
        if cleaned_day_of_month is None or cleaned_day_of_month < 1 or cleaned_day_of_month > 31:
            raise BadRequest("Choose a day of month for monthly recurring work.")
        cleaned_day_of_week = None

    if starts_on is None:
        raise BadRequest("Choose a start date for recurring work.")
    if ends_on is not None and ends_on < starts_on:
        raise BadRequest("End date must be on or after the start date.")
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("Default end time must be after the default start time.")

    if status not in RecurringWork.STATUSES:
        raise BadRequest("Choose a valid recurring work status.")

    return {
        "title": cleaned_title,
        "frequency": frequency,
        "day_of_week": cleaned_day_of_week,
        "day_of_month": cleaned_day_of_month,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
        "notes": (notes or "").strip() or None,
    }


def create_recurring_work(
    customer_id: int,
    *,
    title: str,
    frequency: str,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    status: str = "active",
    notes: str | None = None,
) -> RecurringWork:
    customer = get_customer(customer_id)
    values = _normalize_recurring_work_values(
        title=title,
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        status=status,
        notes=notes,
    )

    recurring_work = RecurringWork(customer_id=customer.id, **values)
    db.session.add(recurring_work)
    db.session.commit()
    return recurring_work


def update_recurring_work(
    recurring_work_id: int,
    *,
    title: str,
    frequency: str,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    status: str = "active",
    notes: str | None = None,
) -> RecurringWork:
    recurring_work = get_recurring_work(recurring_work_id)
    values = _normalize_recurring_work_values(
        title=title,
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        status=status,
        notes=notes,
    )

    recurring_work.title = values["title"]
    recurring_work.frequency = values["frequency"]
    recurring_work.day_of_week = values["day_of_week"]
    recurring_work.day_of_month = values["day_of_month"]
    recurring_work.starts_on = values["starts_on"]
    recurring_work.ends_on = values["ends_on"]
    recurring_work.start_time = values["start_time"]
    recurring_work.end_time = values["end_time"]
    recurring_work.status = values["status"]
    recurring_work.notes = values["notes"]
    db.session.commit()
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


def list_scheduled_appointments(
    start_date: date,
    end_date: date,
    status: str | None = None,
    staff_id: int | None = None,
    sort_by: str = "soonest",
    exclude_cancelled: bool = True,
) -> list[Appointment]:
    statement = select(Appointment).where(
        Appointment.scheduled_date >= start_date,
        Appointment.scheduled_date <= end_date,
    )

    if exclude_cancelled:
        statement = statement.where(Appointment.status != "Cancelled")

    if status and status != "all":
        statement = statement.where(Appointment.status == status)

    if staff_id and staff_id != 0:
        statement = statement.where(Appointment.assigned_staff.any(StaffMember.id == staff_id))

    order_clause = [Appointment.scheduled_date, Appointment.start_time, Appointment.id]
    if sort_by == "latest":
        order_clause = [Appointment.scheduled_date.desc(), Appointment.start_time.desc(), Appointment.id.desc()]
    elif sort_by == "status":
        order_clause = [Appointment.status, Appointment.scheduled_date, Appointment.start_time, Appointment.id]
    elif sort_by == "customer":
        statement = statement.outerjoin(Appointment.customer)
        order_clause = [Customer.primary_name, Appointment.scheduled_date, Appointment.start_time, Appointment.id]

    statement = statement.options(
        selectinload(Appointment.quote_request),
        selectinload(Appointment.customer),
        selectinload(Appointment.assigned_staff),
    ).order_by(*order_clause)

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
    quote_request.sync_status()
    db.session.commit()
    return quote_request


def mark_quote_request_viewed(request_id: int) -> QuoteRequest:
    quote_request = get_quote_request(request_id)
    has_changes = False
    if quote_request.first_viewed_at is None:
        quote_request.first_viewed_at = datetime.now(timezone.utc)
        has_changes = True

    previous_status = quote_request.status
    quote_request.sync_status()
    if quote_request.status != previous_status:
        has_changes = True

    if has_changes:
        db.session.commit()

    return quote_request


def get_request_quote(quote_id: int) -> RequestQuote:
    request_quote = db.session.get(RequestQuote, quote_id)
    if request_quote is None:
        raise NotFound("Quote not found.")
    return request_quote


def create_request_quote(request_id: int, amount, description: str | None = None) -> RequestQuote:
    quote_request = get_quote_request(request_id)
    if amount is None:
        raise BadRequest("Enter a quote amount before saving.")

    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise BadRequest("Enter a valid quote amount.")

    if amount < 0:
        raise BadRequest("Quote amount cannot be negative.")

    if quote_request.first_viewed_at is None:
        quote_request.first_viewed_at = datetime.now(timezone.utc)

    request_quote = RequestQuote(
        quote_request_id=quote_request.id,
        amount=amount,
        description=(description or "").strip() or None,
        decision="Pending",
    )
    db.session.add(request_quote)
    quote_request.quotes.append(request_quote)
    quote_request.sync_status()
    db.session.commit()
    return request_quote


def update_request_quote_decision(quote_id: int, decision: str) -> RequestQuote:
    normalized_decision = (decision or "").strip().capitalize()
    if normalized_decision not in RequestQuote.DECISIONS:
        raise BadRequest("Choose a valid quote decision.")

    request_quote = get_request_quote(quote_id)
    request_quote.decision = normalized_decision
    request_quote.quote_request.sync_status()
    db.session.commit()
    return request_quote


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
