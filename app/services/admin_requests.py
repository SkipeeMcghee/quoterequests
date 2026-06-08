from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
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
from app.services.service_catalog import is_services_enabled, resolve_service_options_by_ids
from app.services.uploads import save_customer_photos


_APPOINTMENT_TITLE_UNSET = object()
_BUSINESS_NAME_SUFFIXES = {
    "llc",
    "inc",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "llp",
    "pllc",
    "plc",
}
_BUSINESS_NAME_HINTS = {
    "services",
    "service",
    "solutions",
    "solution",
    "cleaning",
    "construction",
    "contracting",
    "contractors",
    "landscaping",
    "plumbing",
    "electric",
    "electrical",
    "painting",
    "roofing",
    "maintenance",
    "industries",
    "systems",
    "group",
    "agency",
    "studio",
    "studios",
    "design",
    "works",
    "holdings",
    "properties",
    "realty",
    "motors",
    "auto",
    "garage",
    "clinic",
    "church",
    "ministries",
    "school",
    "restaurant",
    "cafe",
    "salon",
    "shop",
}
_RECURRING_WORK_MANAGED_APPOINTMENT_STATUSES = {"Requested", "Scheduled"}


@dataclass(frozen=True)
class RecurringWorkSyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0

    @property
    def total_changes(self) -> int:
        return self.created + self.updated + self.deleted


@dataclass(frozen=True)
class RecurringWorkScheduleState:
    recurring_work_id: int
    customer_id: int
    quote_request_id: int | None
    title: str | None
    frequency: str
    recurrence_config: dict[str, object] | None
    day_of_week: int | None
    day_of_month: int | None
    starts_on: date
    ends_on: date | None
    start_time: time | None
    end_time: time | None
    status: str


@dataclass
class RecurringWorkSyncPlan:
    schedule_state: RecurringWorkScheduleState
    window_start: date
    window_end: date
    create_dates: list[date]
    appointments_to_update: list[Appointment]
    appointments_to_delete: list[Appointment]
    protected_appointments: list[Appointment]
    unchanged_appointments: list[Appointment]
    service_options: list[ServiceOption] | None

    @property
    def created_count(self) -> int:
        return len(self.create_dates)

    @property
    def updated_count(self) -> int:
        return len(self.appointments_to_update)

    @property
    def deleted_count(self) -> int:
        return len(self.appointments_to_delete)

    @property
    def protected_count(self) -> int:
        return len(self.protected_appointments)

    @property
    def unchanged_count(self) -> int:
        return len(self.unchanged_appointments)

    @property
    def total_changes(self) -> int:
        return self.created_count + self.updated_count + self.deleted_count


def _clean_customer_name_value(value: str | None) -> str | None:
    return (value or "").strip() or None


def _customer_individual_name(customer: Customer) -> str | None:
    individual_name = _clean_customer_name_value(customer.individual_name)
    if individual_name:
        return individual_name
    if customer.display_name_preference != "business":
        return _clean_customer_name_value(customer.primary_name)
    return None


def _customer_business_name(customer: Customer) -> str | None:
    business_name = _clean_customer_name_value(customer.business_name)
    if business_name:
        return business_name
    if customer.display_name_preference == "business":
        return _clean_customer_name_value(customer.primary_name)
    return None


def _guess_customer_name_type(raw_name: str | None) -> str | None:
    cleaned_name = _clean_customer_name_value(raw_name)
    if not cleaned_name:
        return None

    normalized_tokens = [
        token.strip("()")
        for token in cleaned_name.lower().replace(",", " ").replace(".", " ").split()
        if token.strip("()")
    ]

    if any(token in _BUSINESS_NAME_SUFFIXES for token in normalized_tokens):
        return "business"
    if any(token in _BUSINESS_NAME_HINTS for token in normalized_tokens):
        return "business"
    if "&" in cleaned_name and any(token in {"partners", "sons", "associates"} for token in normalized_tokens):
        return "business"
    return "individual"


def _set_customer_name_state(
    customer: Customer,
    *,
    individual_name: str | None,
    business_name: str | None,
    display_name_preference: str | None,
) -> None:
    customer.individual_name = _clean_customer_name_value(individual_name)
    customer.business_name = _clean_customer_name_value(business_name)
    customer.display_name_preference = (display_name_preference or "").strip().lower() or None
    customer.sync_primary_name()


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

    submitted_name = _clean_customer_name_value(quote_request.full_name)
    guessed_name_type = _guess_customer_name_type(submitted_name) or "individual"
    primary_phone = (quote_request.phone or "").strip() or None
    primary_email = (quote_request.email or "").strip().lower() or None
    primary_city = quote_request.city.strip() if quote_request.city else None

    customer = Customer(
        primary_phone=primary_phone,
        primary_email=primary_email,
        primary_city=primary_city,
        billing_amount=None,
        billing_frequency=None,
    )
    _set_customer_name_state(
        customer,
        individual_name=submitted_name if guessed_name_type != "business" else None,
        business_name=submitted_name if guessed_name_type == "business" else None,
        display_name_preference=guessed_name_type,
    )
    db.session.add(customer)
    db.session.flush()

    if customer.individual_name:
        db.session.add(
            CustomerField(
                customer_id=customer.id,
                kind="name",
                value=customer.individual_name,
                is_primary=True,
                source_quote_request_id=quote_request.id,
            )
        )
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


def unlink_quote_request_from_customer(request_id: int) -> QuoteRequest:
    quote_request = get_quote_request(request_id)
    if quote_request.customer_id is None:
        raise BadRequest("Request is not linked to a customer.")

    quote_request.customer = None
    for appointment in quote_request.appointments:
        appointment.customer = None

    db.session.commit()
    return quote_request


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
        primary_phone=(primary_phone or "").strip() or None,
        primary_email=(primary_email or "").strip().lower() or None,
        primary_city=cleaned_city,
        billing_amount=None,
        billing_frequency=None,
    )
    _set_customer_name_state(
        customer,
        individual_name=cleaned_name,
        business_name=None,
        display_name_preference="individual",
    )
    db.session.add(customer)
    db.session.flush()

    if customer.individual_name:
        db.session.add(CustomerField(customer_id=customer.id, kind="name", value=customer.individual_name, is_primary=True))
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
    compensation_amount=None,
    compensation_frequency: str | None = None,
    notes: str | None = None,
    service_ids: list[int] | None = None,
) -> StaffMember:
    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Staff member name cannot be blank.")

    normalized_compensation_amount, normalized_compensation_frequency = _normalize_staff_compensation(
        compensation_amount,
        compensation_frequency,
    )

    staff_member = StaffMember(
        display_name=cleaned_name,
        phone=(phone or "").strip() or None,
        email=(email or "").strip().lower() or None,
        role_title=(role_title or "").strip() or None,
        worker_type=worker_type,
        status=status,
        compensation_amount=normalized_compensation_amount,
        compensation_frequency=normalized_compensation_frequency,
        notes=(notes or "").strip() or None,
    )
    if service_ids and is_services_enabled():
        staff_member.services = resolve_service_options_by_ids(service_ids)
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
    compensation_amount=None,
    compensation_frequency: str | None = None,
    notes: str | None = None,
    service_ids: list[int] | None = None,
) -> StaffMember:
    staff_member = db.session.get(StaffMember, staff_member_id)
    if staff_member is None:
        raise NotFound("Staff member not found.")

    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Staff member name cannot be blank.")

    normalized_compensation_amount, normalized_compensation_frequency = _normalize_staff_compensation(
        compensation_amount,
        compensation_frequency,
    )

    staff_member.display_name = cleaned_name
    staff_member.phone = (phone or "").strip() or None
    staff_member.email = (email or "").strip().lower() or None
    staff_member.role_title = (role_title or "").strip() or None
    staff_member.worker_type = worker_type
    staff_member.status = status
    staff_member.compensation_amount = normalized_compensation_amount
    staff_member.compensation_frequency = normalized_compensation_frequency
    staff_member.notes = (notes or "").strip() or None
    if service_ids is not None and is_services_enabled():
        staff_member.services = resolve_service_options_by_ids(service_ids)
    db.session.commit()
    return staff_member


def update_staff_member_notes(staff_member_id: int, notes: str | None = None) -> StaffMember:
    staff_member = db.session.get(StaffMember, staff_member_id)
    if staff_member is None:
        raise NotFound("Staff member not found.")

    staff_member.notes = (notes or "").strip() or None
    db.session.commit()
    return staff_member


def _normalize_staff_compensation(compensation_amount, compensation_frequency: str | None) -> tuple[Decimal | None, str | None]:
    normalized_frequency = (compensation_frequency or "").strip().lower() or None

    if compensation_amount is not None and compensation_amount != "":
        try:
            normalized_amount = Decimal(str(compensation_amount))
        except (InvalidOperation, ValueError):
            raise BadRequest("Enter a valid compensation amount.")
        if normalized_amount < 0:
            raise BadRequest("Compensation amount cannot be negative.")
    else:
        normalized_amount = None

    if normalized_amount is None and normalized_frequency is None:
        return None, None
    if normalized_amount is None:
        raise BadRequest("Enter a compensation amount.")
    if normalized_frequency is None:
        raise BadRequest("Choose a compensation frequency.")

    valid_frequencies = {value for value, _label in StaffMember.COMPENSATION_FREQUENCY_CHOICES}
    if normalized_frequency not in valid_frequencies:
        raise BadRequest("Choose a valid compensation frequency.")

    return normalized_amount, normalized_frequency


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


def _resolve_service_options(service_ids: list[int] | None) -> list[ServiceOption]:
    return resolve_service_options_by_ids(service_ids)


def _default_quote_request_services(quote_request: QuoteRequest | None) -> list[ServiceOption]:
    if quote_request is None or not is_services_enabled():
        return []
    return list(quote_request.services)


def _clean_appointment_title(raw_title: object) -> str | None:
    if raw_title is None:
        return None
    if not isinstance(raw_title, str):
        raise BadRequest("Enter a valid appointment title.")
    return raw_title.strip() or None


def _resolve_staff_members(staff_ids: list[int] | None) -> list[StaffMember]:
    if not staff_ids:
        return []

    normalized_staff_ids = sorted(set(staff_ids))
    staff_members = list(
        StaffMember.query.filter(StaffMember.id.in_(normalized_staff_ids)).order_by(StaffMember.display_name).all()
    )
    if len(staff_members) != len(normalized_staff_ids):
        raise NotFound("One or more staff members were not found.")
    return staff_members


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
    existing_windows = [window for window in staff_member.availability_windows if window.day_of_week == day_of_week]
    for window in existing_windows:
        if start_time < window.end_time and window.start_time < end_time:
            raise BadRequest("Availability windows cannot overlap on the same day.")

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


def _coerce_staff_availability_time(value) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        raise BadRequest("Availability times must be valid HH:MM values.")
    try:
        return time.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError as exc:
        raise BadRequest("Availability times must be valid HH:MM values.") from exc


def sync_staff_availability(staff_member_id: int, windows_payload: list[dict]) -> list[StaffAvailability]:
    staff_member = db.session.get(StaffMember, staff_member_id)
    if staff_member is None:
        raise NotFound("Staff member not found.")
    if not isinstance(windows_payload, list):
        raise BadRequest("Availability data must be a list of windows.")

    existing_windows = {window.id: window for window in staff_member.availability_windows}
    normalized_windows = []
    seen_ids: set[int] = set()

    for item in windows_payload:
        if not isinstance(item, dict):
            raise BadRequest("Availability windows must be objects.")

        raw_id = item.get("id")
        availability_id = None
        if raw_id not in (None, ""):
            try:
                availability_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise BadRequest("Availability window ids must be valid integers.") from exc
            if availability_id in seen_ids:
                raise BadRequest("Duplicate availability windows were submitted.")
            if availability_id not in existing_windows:
                raise NotFound("Staff availability not found.")
            seen_ids.add(availability_id)

        try:
            day_of_week = int(item.get("day_of_week"))
        except (TypeError, ValueError) as exc:
            raise BadRequest("Availability day values must be between 0 and 6.") from exc
        if day_of_week < 0 or day_of_week > 6:
            raise BadRequest("Availability day values must be between 0 and 6.")

        start_time = _coerce_staff_availability_time(item.get("start_time"))
        end_time = _coerce_staff_availability_time(item.get("end_time"))
        if end_time <= start_time:
            raise BadRequest("Availability end time must be after the start time.")

        normalized_windows.append(
            {
                "id": availability_id,
                "day_of_week": day_of_week,
                "start_time": start_time,
                "end_time": end_time,
                "notes": (item.get("notes") or "").strip() or None,
            }
        )

    sorted_windows = sorted(
        normalized_windows,
        key=lambda item: (
            item["day_of_week"],
            item["start_time"],
            item["end_time"],
            item["id"] or 0,
        ),
    )
    previous_by_day: dict[int, dict] = {}
    for item in sorted_windows:
        previous = previous_by_day.get(item["day_of_week"])
        if previous is not None and item["start_time"] < previous["end_time"]:
            raise BadRequest("Availability windows cannot overlap on the same day.")
        previous_by_day[item["day_of_week"]] = item

    for existing_id, existing_window in existing_windows.items():
        if existing_id not in seen_ids:
            db.session.delete(existing_window)

    for item in normalized_windows:
        if item["id"] is None:
            availability = StaffAvailability(staff_member_id=staff_member_id)
            db.session.add(availability)
        else:
            availability = existing_windows[item["id"]]

        availability.day_of_week = item["day_of_week"]
        availability.start_time = item["start_time"]
        availability.end_time = item["end_time"]
        availability.notes = item["notes"]

    db.session.commit()
    db.session.refresh(staff_member)
    return list(staff_member.availability_windows)


def create_scheduled_work(
    request_id: int | None = None,
    customer_id: int | None = None,
    new_customer_name: str | None = None,
    new_customer_phone: str | None = None,
    new_customer_email: str | None = None,
    new_customer_city: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str = "Scheduled",
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    service_ids: list[int] | None = None,
    staff_ids: list[int] | None = None,
    title: str | None = None,
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

    selected_services = _resolve_service_options(service_ids)
    selected_staff = _resolve_staff_members(staff_ids)

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
        title=_clean_appointment_title(title),
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        status=status,
        customer_notes=(customer_notes or "").strip() or None,
        internal_notes=(internal_notes or "").strip() or None,
    )
    db.session.add(appointment)
    appointment.services = selected_services or _default_quote_request_services(quote_request)
    for staff_member in selected_staff:
        appointment.staff_assignments.append(AppointmentStaffAssignment(staff_member_id=staff_member.id))
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
    if _customer_individual_name(source) and not _customer_individual_name(target):
        target.individual_name = _customer_individual_name(source)
    if _customer_business_name(source) and not _customer_business_name(target):
        target.business_name = _customer_business_name(source)
    if source.display_name_preference in Customer.DISPLAY_NAME_PREFERENCES and target.display_name_preference not in Customer.DISPLAY_NAME_PREFERENCES:
        target.display_name_preference = source.display_name_preference
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

    target.sync_primary_name()
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
            customer.individual_name = cleaned_value
            customer.sync_primary_name()
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
        customer.individual_name = field.value
        customer.sync_primary_name()
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
    normalized_amount, normalized_frequency = _normalize_billing_values(
        billing_amount,
        billing_frequency,
        Customer.BILLING_FREQUENCIES,
    )
    customer.billing_amount = normalized_amount
    customer.billing_frequency = normalized_frequency

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


def update_customer_info(
    customer_id: int,
    individual_name: str | None,
    business_name: str | None,
    display_name_preference: str | None,
    primary_phone: str | None,
    primary_email: str | None,
    primary_city: str | None,
) -> Customer:
    customer = get_customer(customer_id)
    cleaned_individual_name = _clean_customer_name_value(individual_name)
    cleaned_business_name = _clean_customer_name_value(business_name)
    if not (cleaned_individual_name or cleaned_business_name):
        raise BadRequest("Enter an individual name or a business name.")
    cleaned_city = (primary_city or "").strip()
    if not cleaned_city:
        raise BadRequest("Customer city cannot be blank.")

    _set_customer_name_state(
        customer,
        individual_name=cleaned_individual_name,
        business_name=cleaned_business_name,
        display_name_preference=display_name_preference,
    )
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
            selectinload(Appointment.services),
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


def _resolve_appointment_status(
    *,
    scheduled_date,
    requested_status: str | None = None,
    current_status: str | None = None,
) -> str:
    if requested_status is not None:
        if requested_status not in APPOINTMENT_STATUSES:
            raise BadRequest("Choose a valid appointment status.")
        return requested_status

    if current_status in {"Completed", "Cancelled", "No Show"}:
        return current_status

    return "Scheduled" if scheduled_date is not None else "Requested"


def create_appointment(
    request_id: int,
    requested_date,
    requested_time=None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    confirmed_date=None,
    confirmed_time=None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str | None = None,
    previous_appointment_id: int | None = None,
    staff_ids: list[int] | None = None,
    service_ids: list[int] | None = None,
    title: str | None = None,
) -> Appointment:
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

    quote_request = get_quote_request(request_id)
    selected_services = _resolve_service_options(service_ids)
    selected_staff = _resolve_staff_members(staff_ids)
    appointment = Appointment(
        customer_id=quote_request.customer_id,
        quote_request_id=quote_request.id,
        title=_clean_appointment_title(title),
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        requested_date=requested_date,
        requested_time=requested_time,
        confirmed_date=confirmed_date,
        confirmed_time=confirmed_time,
        customer_notes=customer_notes,
        internal_notes=internal_notes,
        status=_resolve_appointment_status(
            scheduled_date=scheduled_date,
            requested_status=status,
        ),
        previous_appointment_id=previous_appointment_id,
    )
    appointment.services = selected_services or _default_quote_request_services(quote_request)
    for staff_member in selected_staff:
        appointment.staff_assignments.append(AppointmentStaffAssignment(staff_member_id=staff_member.id))
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
        recurring_exception=appointment.recurring_exception,
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
    requested_time=None,
    confirmed_date=None,
    confirmed_time=None,
    customer_notes: str | None = None,
    internal_notes: str | None = None,
    scheduled_date=None,
    start_time=None,
    end_time=None,
    status: str | None = None,
    title: object = _APPOINTMENT_TITLE_UNSET,
) -> Appointment:
    appointment = get_appointment(appointment_id)
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("End time must be after the start time.")

    if title is not _APPOINTMENT_TITLE_UNSET:
        appointment.title = _clean_appointment_title(title)
    appointment.requested_date = requested_date
    appointment.requested_time = requested_time
    appointment.confirmed_date = confirmed_date
    appointment.confirmed_time = confirmed_time
    appointment.customer_notes = customer_notes
    appointment.internal_notes = internal_notes
    appointment.scheduled_date = scheduled_date
    appointment.start_time = start_time
    appointment.end_time = end_time
    appointment.status = _resolve_appointment_status(
        scheduled_date=scheduled_date,
        requested_status=status,
        current_status=appointment.status,
    )
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


def delete_appointment(appointment_id: int) -> Appointment:
    appointment = get_appointment(appointment_id)

    for rescheduled_appointment in list(appointment.rescheduled_appointments):
        rescheduled_appointment.previous_appointment_id = appointment.previous_appointment_id

    quote_request = appointment.quote_request
    db.session.delete(appointment)
    db.session.flush()

    if quote_request is not None:
        quote_request.sync_status()

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
    recurrence_config: dict[str, object] | None = None,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    billing_amount=None,
    billing_frequency: str | None = None,
    status: str = "active",
    notes: str | None = None,
) -> dict[str, object]:
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise BadRequest("Enter a service or work title.")

    requested_frequency = (frequency or "").strip().lower() or "custom"
    if requested_frequency not in RecurringWork.FREQUENCIES:
        raise BadRequest("Choose a valid recurring frequency preset.")

    normalized_frequency, normalized_recurrence_config, cleaned_day_of_week, cleaned_day_of_month = _normalize_recurrence_config_input(
        frequency=requested_frequency,
        recurrence_config=recurrence_config,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
    )

    if starts_on is None:
        raise BadRequest("Choose a start date for recurring work.")
    if ends_on is not None and ends_on < starts_on:
        raise BadRequest("End date must be on or after the start date.")
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise BadRequest("Default end time must be after the default start time.")

    if status not in RecurringWork.STATUSES:
        raise BadRequest("Choose a valid recurring work status.")

    normalized_billing_amount, normalized_billing_frequency = _normalize_billing_values(
        billing_amount,
        billing_frequency,
        RecurringWork.BILLING_FREQUENCIES,
    )

    return {
        "title": cleaned_title,
        "frequency": normalized_frequency,
        "recurrence_config": normalized_recurrence_config,
        "day_of_week": cleaned_day_of_week,
        "day_of_month": cleaned_day_of_month,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "start_time": start_time,
        "end_time": end_time,
        "billing_amount": normalized_billing_amount,
        "billing_frequency": normalized_billing_frequency,
        "status": status,
        "notes": (notes or "").strip() or None,
    }


def _normalize_billing_values(
    billing_amount,
    billing_frequency: str | None,
    valid_frequencies: tuple[str, ...],
) -> tuple[Decimal | None, str | None]:
    normalized_frequency = (billing_frequency or "").strip().lower() or None

    if billing_amount is not None and billing_amount != "":
        try:
            normalized_amount = Decimal(str(billing_amount))
        except (InvalidOperation, ValueError):
            raise BadRequest("Enter a valid billing amount.")
        if normalized_amount < 0:
            raise BadRequest("Billing amount cannot be negative.")
    else:
        normalized_amount = None

    if normalized_frequency and normalized_frequency not in valid_frequencies:
        raise BadRequest("Choose a valid billing frequency.")

    if (normalized_amount is None) ^ (normalized_frequency is None):
        raise BadRequest("Enter both billing amount and billing frequency.")

    return normalized_amount, normalized_frequency


def create_recurring_work(
    customer_id: int,
    *,
    title: str,
    frequency: str,
    recurrence_config: dict[str, object] | None = None,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    billing_amount=None,
    billing_frequency: str | None = None,
    status: str = "active",
    notes: str | None = None,
) -> RecurringWork:
    customer = get_customer(customer_id)
    values = _normalize_recurring_work_values(
        title=title,
        frequency=frequency,
        recurrence_config=recurrence_config,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        billing_amount=billing_amount,
        billing_frequency=billing_frequency,
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
    recurrence_config: dict[str, object] | None = None,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    billing_amount=None,
    billing_frequency: str | None = None,
    status: str = "active",
    notes: str | None = None,
) -> RecurringWork:
    recurring_work = get_recurring_work(recurring_work_id)
    values = _normalize_recurring_work_values(
        title=title,
        frequency=frequency,
        recurrence_config=recurrence_config,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        billing_amount=billing_amount,
        billing_frequency=billing_frequency,
        status=status,
        notes=notes,
    )

    recurring_work.title = values["title"]
    recurring_work.frequency = values["frequency"]
    recurring_work.recurrence_config = values["recurrence_config"]
    recurring_work.day_of_week = values["day_of_week"]
    recurring_work.day_of_month = values["day_of_month"]
    recurring_work.starts_on = values["starts_on"]
    recurring_work.ends_on = values["ends_on"]
    recurring_work.start_time = values["start_time"]
    recurring_work.end_time = values["end_time"]
    recurring_work.billing_amount = values["billing_amount"]
    recurring_work.billing_frequency = values["billing_frequency"]
    recurring_work.status = values["status"]
    recurring_work.notes = values["notes"]
    db.session.commit()
    return recurring_work


def _build_recurring_work_schedule_state(
    recurring_work: RecurringWork,
    *,
    values: dict[str, object] | None = None,
) -> RecurringWorkScheduleState:
    normalized_values = values or {}
    return RecurringWorkScheduleState(
        recurring_work_id=recurring_work.id,
        customer_id=int(normalized_values.get("customer_id", recurring_work.customer_id)),
        quote_request_id=normalized_values.get("quote_request_id", recurring_work.quote_request_id),
        title=normalized_values.get("title", recurring_work.title),
        frequency=str(normalized_values.get("frequency", recurring_work.frequency)),
        recurrence_config=normalized_values.get("recurrence_config", getattr(recurring_work, "recurrence_config", None)),
        day_of_week=normalized_values.get("day_of_week", recurring_work.day_of_week),
        day_of_month=normalized_values.get("day_of_month", recurring_work.day_of_month),
        starts_on=normalized_values.get("starts_on", recurring_work.starts_on),
        ends_on=normalized_values.get("ends_on", recurring_work.ends_on),
        start_time=normalized_values.get("start_time", recurring_work.start_time),
        end_time=normalized_values.get("end_time", recurring_work.end_time),
        status=str(normalized_values.get("status", recurring_work.status)),
    )


def _resolve_recurring_work_service_options_for_title(title: str | None) -> list[ServiceOption] | None:
    if not is_services_enabled():
        return None

    cleaned_title = (title or "").strip()
    if not cleaned_title:
        return None

    service = db.session.scalar(select(ServiceOption).where(ServiceOption.name == cleaned_title))
    if service is None:
        return None
    return [service]


def _normalize_recurrence_weekdays(raw_values) -> tuple[int, ...]:
    if raw_values in (None, ""):
        return ()

    if isinstance(raw_values, (int, str)):
        raw_iterable = [raw_values]
    else:
        raw_iterable = list(raw_values)

    normalized: list[int] = []
    seen_values: set[int] = set()
    for raw_value in raw_iterable:
        try:
            weekday = int(raw_value)
        except (TypeError, ValueError):
            continue

        if weekday < 0 or weekday > 6 or weekday in seen_values:
            continue

        seen_values.add(weekday)
        normalized.append(weekday)

    return tuple(sorted(normalized))


def _normalize_recurrence_month_days(raw_values) -> tuple[int, ...]:
    if raw_values in (None, ""):
        return ()

    if isinstance(raw_values, (int, str)):
        raw_iterable = [raw_values]
    else:
        raw_iterable = list(raw_values)

    normalized: list[int] = []
    seen_values: set[int] = set()
    for raw_value in raw_iterable:
        try:
            month_day = int(raw_value)
        except (TypeError, ValueError):
            continue

        if month_day < 1 or month_day > 31 or month_day in seen_values:
            continue

        seen_values.add(month_day)
        normalized.append(month_day)

    return tuple(sorted(normalized))


def _default_recurrence_config(
    *,
    frequency: str,
    day_of_week: int | None,
    day_of_month: int | None,
) -> dict[str, object]:
    if frequency in {"weekly", "biweekly"}:
        return {
            "unit": "week",
            "interval": 2 if frequency == "biweekly" else 1,
            "weekdays": list(_normalize_recurrence_weekdays([day_of_week])),
            "month_days": [],
        }

    if frequency in {"monthly", "semi_monthly", "bimonthly"}:
        return {
            "unit": "month",
            "interval": 2 if frequency == "bimonthly" else 1,
            "weekdays": [],
            "month_days": list(_normalize_recurrence_month_days([day_of_month])),
        }

    return {
        "unit": "month" if day_of_month is not None else "week",
        "interval": 1,
        "weekdays": list(_normalize_recurrence_weekdays([day_of_week])),
        "month_days": list(_normalize_recurrence_month_days([day_of_month])),
    }


def _resolve_recurrence_config(recurring_work: RecurringWork | RecurringWorkScheduleState) -> dict[str, object]:
    raw_config = getattr(recurring_work, "recurrence_config", None) or _default_recurrence_config(
        frequency=recurring_work.frequency,
        day_of_week=recurring_work.day_of_week,
        day_of_month=recurring_work.day_of_month,
    )

    unit = str(raw_config.get("unit") or "").strip().lower()
    if unit not in {"week", "month"}:
        unit = "week" if recurring_work.frequency == "weekly" else "month"

    try:
        interval = int(raw_config.get("interval") or 1)
    except (TypeError, ValueError):
        interval = 1
    if interval < 1:
        interval = 1

    weekdays = list(_normalize_recurrence_weekdays(raw_config.get("weekdays")))
    month_days = list(_normalize_recurrence_month_days(raw_config.get("month_days")))

    if unit == "week" and not weekdays:
        weekdays = list(_normalize_recurrence_weekdays([recurring_work.day_of_week]))
    if unit == "month" and not month_days:
        month_days = list(_normalize_recurrence_month_days([recurring_work.day_of_month]))

    return {
        "unit": unit,
        "interval": interval,
        "weekdays": weekdays,
        "month_days": month_days,
    }


def _classify_recurrence_frequency(recurrence_config: dict[str, object]) -> str:
    unit = str(recurrence_config["unit"])
    interval = int(recurrence_config["interval"])
    weekdays = list(recurrence_config["weekdays"])
    month_days = list(recurrence_config["month_days"])

    if unit == "week" and interval == 1 and len(weekdays) == 1:
        return "weekly"
    if unit == "week" and interval == 2 and len(weekdays) == 1:
        return "biweekly"
    if unit == "month" and interval == 1 and len(month_days) == 1:
        return "monthly"
    if unit == "month" and interval == 1 and len(month_days) == 2:
        return "semi_monthly"
    if unit == "month" and interval == 2 and len(month_days) == 1:
        return "bimonthly"
    return "custom"


def _normalize_recurrence_config_input(
    *,
    frequency: str,
    recurrence_config: dict[str, object] | None,
    day_of_week: int | None,
    day_of_month: int | None,
) -> tuple[str, dict[str, object], int | None, int | None]:
    raw_config = recurrence_config or _default_recurrence_config(
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
    )

    unit = str(raw_config.get("unit") or "").strip().lower()
    if unit not in {"week", "month"}:
        raise BadRequest("Choose whether this recurring plan repeats by week or by month.")

    try:
        interval = int(raw_config.get("interval") or 1)
    except (TypeError, ValueError):
        raise BadRequest("Choose a valid repeat interval.")
    if interval < 1:
        raise BadRequest("Repeat interval must be at least 1.")

    weekdays = list(_normalize_recurrence_weekdays(raw_config.get("weekdays")))
    month_days = list(_normalize_recurrence_month_days(raw_config.get("month_days")))

    if unit == "week" and not weekdays:
        raise BadRequest("Choose at least one weekday for this recurring plan.")
    if unit == "month" and not month_days:
        raise BadRequest("Choose at least one day of month for this recurring plan.")

    normalized_config = {
        "unit": unit,
        "interval": interval,
        "weekdays": weekdays,
        "month_days": month_days,
    }
    normalized_frequency = _classify_recurrence_frequency(normalized_config)
    primary_day_of_week = weekdays[0] if weekdays else None
    primary_day_of_month = month_days[0] if month_days else None

    return normalized_frequency, normalized_config, primary_day_of_week, primary_day_of_month


def _iter_recurring_work_candidate_dates(
    recurring_work: RecurringWork | RecurringWorkScheduleState,
    *,
    start_date: date,
    window_end: date,
) -> list[date]:
    if start_date > window_end:
        return []

    candidate_dates: list[date] = []
    recurrence_config = _resolve_recurrence_config(recurring_work)

    if recurrence_config["unit"] == "week":
        weekdays = recurrence_config["weekdays"]
        if not weekdays:
            raise BadRequest("Weekly recurring work requires at least one weekday.")

        interval = int(recurrence_config["interval"])
        anchor_week_start = recurring_work.starts_on - timedelta(days=recurring_work.starts_on.weekday())
        candidate = start_date
        while candidate <= window_end:
            weeks_since_anchor = (candidate - anchor_week_start).days // 7
            if weeks_since_anchor >= 0 and weeks_since_anchor % interval == 0 and candidate.weekday() in weekdays:
                if candidate >= recurring_work.starts_on:
                    candidate_dates.append(candidate)
            candidate += timedelta(days=1)
        return candidate_dates

    if recurrence_config["unit"] == "month":
        month_days = recurrence_config["month_days"]
        if not month_days:
            raise BadRequest("Monthly recurring work requires at least one day of month.")

        interval = int(recurrence_config["interval"])
        candidate_year = start_date.year
        candidate_month = start_date.month

        while True:
            months_since_anchor = ((candidate_year - recurring_work.starts_on.year) * 12) + (candidate_month - recurring_work.starts_on.month)
            if months_since_anchor >= 0 and months_since_anchor % interval == 0:
                days_in_candidate_month = monthrange(candidate_year, candidate_month)[1]
                for candidate_day in month_days:
                    if candidate_day > days_in_candidate_month:
                        continue
                    candidate = date(candidate_year, candidate_month, candidate_day)
                    if start_date <= candidate <= window_end and candidate >= recurring_work.starts_on:
                        candidate_dates.append(candidate)

            if candidate_year > window_end.year or (candidate_year == window_end.year and candidate_month >= window_end.month):
                break
            if candidate_month == 12:
                candidate_month = 1
                candidate_year += 1
            else:
                candidate_month += 1
        return candidate_dates

    raise BadRequest("Recurring work must use a valid recurrence unit.")


def _appointment_matches_recurring_work_defaults(
    appointment: Appointment,
    schedule_state: RecurringWorkScheduleState,
    *,
    service_options: list[ServiceOption] | None,
) -> bool:
    expected_title = schedule_state.title or "Recurring work"

    if appointment.customer_id != schedule_state.customer_id:
        return False
    if appointment.quote_request_id != schedule_state.quote_request_id:
        return False
    if appointment.title != expected_title:
        return False
    if appointment.start_time != schedule_state.start_time:
        return False
    if appointment.end_time != schedule_state.end_time:
        return False

    if service_options is not None:
        current_service_ids = [service.id for service in appointment.services]
        desired_service_ids = [service.id for service in service_options]
        if current_service_ids != desired_service_ids:
            return False

    return True


def _apply_recurring_work_defaults(
    appointment: Appointment,
    schedule_state: RecurringWorkScheduleState,
    *,
    service_options: list[ServiceOption] | None,
) -> None:
    appointment.customer_id = schedule_state.customer_id
    appointment.quote_request_id = schedule_state.quote_request_id
    appointment.title = schedule_state.title or "Recurring work"
    appointment.start_time = schedule_state.start_time
    appointment.end_time = schedule_state.end_time

    if service_options is not None:
        appointment.services = list(service_options)


def _appointment_is_recurring_sync_locked(appointment: Appointment) -> bool:
    return bool(appointment.recurring_exception or appointment.status not in _RECURRING_WORK_MANAGED_APPOINTMENT_STATUSES)


def _build_recurring_work_sync_plan(
    recurring_work: RecurringWork,
    *,
    schedule_state: RecurringWorkScheduleState,
    days_ahead: int = 60,
) -> RecurringWorkSyncPlan:
    if days_ahead < 0:
        raise BadRequest("Generation window cannot be negative.")

    today_value = date.today()
    window_start = max(today_value, schedule_state.starts_on)
    window_end = today_value + timedelta(days=days_ahead)
    if schedule_state.ends_on is not None:
        window_end = min(window_end, schedule_state.ends_on)

    expected_dates: set[date] = set()
    if schedule_state.status == "active" and window_start <= window_end:
        expected_dates = set(
            _iter_recurring_work_candidate_dates(
                schedule_state,
                start_date=window_start,
                window_end=window_end,
            )
        )

    service_options = _resolve_recurring_work_service_options_for_title(schedule_state.title)
    appointments_for_work = sorted(
        db.session.query(Appointment).filter_by(recurring_work_id=recurring_work.id).all(),
        key=lambda appointment: (appointment.scheduled_date or date.max, appointment.id),
    )

    appointments_by_date: dict[date, list[Appointment]] = {}
    for appointment in appointments_for_work:
        if appointment.scheduled_date is None or appointment.scheduled_date < today_value:
            continue
        appointments_by_date.setdefault(appointment.scheduled_date, []).append(appointment)

    create_dates: list[date] = []
    appointments_to_update: list[Appointment] = []
    appointments_to_delete: list[Appointment] = []
    protected_appointments: list[Appointment] = []
    unchanged_appointments: list[Appointment] = []
    occupied_dates: set[date] = set()

    for scheduled_date, appointments_on_date in sorted(appointments_by_date.items()):
        protected_for_date = [
            appointment
            for appointment in appointments_on_date
            if _appointment_is_recurring_sync_locked(appointment)
        ]
        managed_for_date = [
            appointment
            for appointment in appointments_on_date
            if not _appointment_is_recurring_sync_locked(appointment)
        ]

        if protected_for_date:
            protected_appointments.extend(protected_for_date)
            occupied_dates.add(scheduled_date)
            appointments_to_delete.extend(managed_for_date)
            continue

        if scheduled_date not in expected_dates:
            appointments_to_delete.extend(managed_for_date)
            continue

        if managed_for_date:
            keep_appointment = managed_for_date[0]
            if _appointment_matches_recurring_work_defaults(
                keep_appointment,
                schedule_state,
                service_options=service_options,
            ):
                unchanged_appointments.append(keep_appointment)
            else:
                appointments_to_update.append(keep_appointment)
            occupied_dates.add(scheduled_date)
            appointments_to_delete.extend(managed_for_date[1:])

    for candidate_date in sorted(expected_dates - occupied_dates):
        create_dates.append(candidate_date)

    return RecurringWorkSyncPlan(
        schedule_state=schedule_state,
        window_start=window_start,
        window_end=window_end,
        create_dates=create_dates,
        appointments_to_update=appointments_to_update,
        appointments_to_delete=appointments_to_delete,
        protected_appointments=protected_appointments,
        unchanged_appointments=unchanged_appointments,
        service_options=service_options,
    )


def preview_recurring_work_sync(
    recurring_work_id: int,
    *,
    title: str,
    frequency: str,
    recurrence_config: dict[str, object] | None = None,
    day_of_week: int | None,
    day_of_month: int | None,
    starts_on,
    ends_on=None,
    start_time=None,
    end_time=None,
    billing_amount=None,
    billing_frequency: str | None = None,
    status: str = "active",
    notes: str | None = None,
    days_ahead: int = 60,
) -> RecurringWorkSyncPlan:
    recurring_work = get_recurring_work(recurring_work_id)
    values = _normalize_recurring_work_values(
        title=title,
        frequency=frequency,
        recurrence_config=recurrence_config,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        starts_on=starts_on,
        ends_on=ends_on,
        start_time=start_time,
        end_time=end_time,
        billing_amount=billing_amount,
        billing_frequency=billing_frequency,
        status=status,
        notes=notes,
    )
    schedule_state = _build_recurring_work_schedule_state(recurring_work, values=values)
    return _build_recurring_work_sync_plan(
        recurring_work,
        schedule_state=schedule_state,
        days_ahead=days_ahead,
    )


def _apply_recurring_work_sync_plan(recurring_work: RecurringWork, plan: RecurringWorkSyncPlan) -> RecurringWorkSyncResult:
    for appointment in plan.appointments_to_update:
        _apply_recurring_work_defaults(
            appointment,
            plan.schedule_state,
            service_options=plan.service_options,
        )

    for appointment in plan.appointments_to_delete:
        db.session.delete(appointment)

    for candidate_date in plan.create_dates:
        appointment = Appointment(
            customer_id=plan.schedule_state.customer_id,
            quote_request_id=plan.schedule_state.quote_request_id,
            recurring_work_id=recurring_work.id,
            title=plan.schedule_state.title or "Recurring work",
            scheduled_date=candidate_date,
            start_time=plan.schedule_state.start_time,
            end_time=plan.schedule_state.end_time,
            status="Scheduled",
            recurring_exception=False,
            internal_notes=f"Generated from recurring work #{recurring_work.id}",
        )
        if plan.service_options is not None:
            appointment.services = list(plan.service_options)
        db.session.add(appointment)

    if plan.total_changes:
        db.session.commit()

    return RecurringWorkSyncResult(
        created=plan.created_count,
        updated=plan.updated_count,
        deleted=plan.deleted_count,
    )


def sync_recurring_work_appointments(recurring_work_id: int, days_ahead: int = 60) -> RecurringWorkSyncResult:
    recurring_work = get_recurring_work(recurring_work_id)
    plan = _build_recurring_work_sync_plan(
        recurring_work,
        schedule_state=_build_recurring_work_schedule_state(recurring_work),
        days_ahead=days_ahead,
    )
    return _apply_recurring_work_sync_plan(recurring_work, plan)


def set_recurring_appointment_exception(appointment_id: int, *, is_exception: bool) -> Appointment:
    appointment = get_appointment(appointment_id)
    if appointment.recurring_work_id is None:
        raise BadRequest("Only recurring-work appointments can use exception controls.")

    appointment.recurring_exception = is_exception
    db.session.commit()
    return appointment


def archive_recurring_work(recurring_work_id: int) -> RecurringWorkSyncResult:
    recurring_work = get_recurring_work(recurring_work_id)
    today_value = date.today()
    future_managed_appointments = [
        appointment
        for appointment in recurring_work.appointments
        if appointment.scheduled_date
        and appointment.scheduled_date >= today_value
        and not _appointment_is_recurring_sync_locked(appointment)
    ]

    recurring_work.status = "inactive"
    for appointment in future_managed_appointments:
        db.session.delete(appointment)
    db.session.commit()

    return RecurringWorkSyncResult(
        created=0,
        updated=0,
        deleted=len(future_managed_appointments),
    )


def generate_appointments_for_recurring_work(recurring_work_id: int, days_ahead: int = 60) -> int:
    return sync_recurring_work_appointments(recurring_work_id, days_ahead=days_ahead).created


def generate_recurring_appointments_for_customer(customer_id: int, days_ahead: int = 60) -> int:
    customer = get_customer(customer_id)
    total_created = 0
    for recurring_work in customer.recurring_works:
        total_created += sync_recurring_work_appointments(recurring_work.id, days_ahead=days_ahead).created
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
        selectinload(Appointment.services),
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


def create_request_quote(
    request_id: int,
    amount,
    billing_frequency: str,
    description: str | None = None,
) -> RequestQuote:
    quote_request = get_quote_request(request_id)
    if amount is None:
        raise BadRequest("Enter a quote amount before saving.")

    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise BadRequest("Enter a valid quote amount.")

    if amount < 0:
        raise BadRequest("Quote amount cannot be negative.")

    normalized_billing_frequency = (billing_frequency or "").strip().title()
    if normalized_billing_frequency not in RequestQuote.BILLING_FREQUENCIES:
        raise BadRequest("Choose a valid billing frequency.")

    if quote_request.first_viewed_at is None:
        quote_request.first_viewed_at = datetime.now(timezone.utc)

    request_quote = RequestQuote(
        quote_request_id=quote_request.id,
        amount=amount,
        billing_frequency=normalized_billing_frequency,
        description=(description or "").strip() or None,
        decision="Sent",
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


def delete_request_quote(quote_id: int) -> int:
    request_quote = get_request_quote(quote_id)
    quote_request = request_quote.quote_request
    request_id = quote_request.id
    db.session.delete(request_quote)
    db.session.flush()
    if not quote_request.quotes and quote_request.status in {"Quoted", "Accepted", "Rejected"}:
        if quote_request.last_contacted_on:
            quote_request.status = "Contacted"
        elif quote_request.first_viewed_at:
            quote_request.status = "Viewed"
        else:
            quote_request.status = "New"
    quote_request.sync_status()
    db.session.commit()
    return request_id


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
