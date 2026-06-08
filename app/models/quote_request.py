from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Time, event, func, select

from app.extensions import db


QUOTE_REQUEST_STATUSES = ("New", "Viewed", "Contacted", "Quoted", "Accepted", "Rejected", "Scheduled")
REQUEST_QUOTE_DECISIONS = ("Sent", "Accepted", "Rejected")
REQUEST_QUOTE_BILLING_FREQUENCIES = ("Hourly", "Daily", "Weekly", "Biweekly", "Monthly")
REQUEST_TYPES = ("Quote request", "Work request")

APPOINTMENT_STATUSES = ("Requested", "Scheduled", "Completed", "Cancelled", "Rescheduled", "No Show")

quote_request_service_options = db.Table(
    "quote_request_service_options",
    db.Column("quote_request_id", db.Integer, db.ForeignKey("quote_requests.id"), primary_key=True),
    db.Column("service_option_id", db.Integer, db.ForeignKey("service_options.id"), primary_key=True),
)

appointment_service_options = db.Table(
    "appointment_service_options",
    db.Column("appointment_id", db.Integer, db.ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True),
    db.Column("service_option_id", db.Integer, db.ForeignKey("service_options.id", ondelete="CASCADE"), primary_key=True),
)


class ServiceOption(db.Model):
    __tablename__ = "service_options"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=sa.true(), index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0, server_default="0", index=True)

    quote_requests = db.relationship(
        "QuoteRequest",
        secondary=quote_request_service_options,
        back_populates="services",
        order_by="QuoteRequest.id",
    )
    appointments = db.relationship(
        "Appointment",
        secondary=appointment_service_options,
        back_populates="services",
        order_by="Appointment.id",
    )
    staff_members = db.relationship(
        "StaffMember",
        secondary="staff_service_options",
        back_populates="services",
        order_by="StaffMember.display_name",
    )
    gallery_items = db.relationship(
        "GalleryItem",
        back_populates="service",
        order_by="(GalleryItem.display_order, GalleryItem.id)",
    )

    def __str__(self) -> str:
        return self.name

    @classmethod
    def ordered_query(cls, include_inactive: bool = True):
        query = cls.query.order_by(cls.display_order.asc(), cls.name.asc())
        if not include_inactive:
            query = query.filter(cls.is_active.is_(True))
        return query

    @property
    def normalized_description(self) -> str | None:
        return (self.description or "").strip() or None


class QuoteRequest(db.Model):
    __tablename__ = "quote_requests"
    __table_args__ = (
        db.UniqueConstraint("request_type", "request_number", name="uq_quote_requests_type_number"),
    )
    REQUEST_TYPES = ("Quote request", "Work request")

    id = db.Column(db.Integer, primary_key=True)
    request_number = db.Column(db.Integer, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    city = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="New")
    request_type = db.Column(db.String(32), nullable=False, default="Quote request")
    additional_notes = db.Column(db.Text, nullable=True)
    last_contacted_on = db.Column(db.Date, nullable=True)
    first_viewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)

    services = db.relationship(
        "ServiceOption",
        secondary=quote_request_service_options,
        back_populates="quote_requests",
        order_by="(ServiceOption.display_order, ServiceOption.name)",
    )
    appointments = db.relationship(
        "Appointment",
        back_populates="quote_request",
        order_by="Appointment.created_at.desc()",
        cascade="all, delete-orphan",
    )
    photos = db.relationship(
        "RequestPhoto",
        back_populates="quote_request",
        cascade="all, delete-orphan",
        order_by="RequestPhoto.created_at.asc()",
    )
    notes = db.relationship(
        "RequestNote",
        back_populates="quote_request",
        cascade="all, delete-orphan",
        order_by="RequestNote.created_at.desc()",
    )
    quotes = db.relationship(
        "RequestQuote",
        back_populates="quote_request",
        cascade="all, delete-orphan",
        order_by="RequestQuote.created_at.desc()",
    )
    customer = db.relationship("Customer", back_populates="quote_requests")

    @property
    def service_names(self) -> list[str]:
        return [service.name for service in self.services]

    @property
    def service_list_display(self) -> str:
        return ", ".join(self.service_names)

    @property
    def normalized_request_type(self) -> str:
        return self.request_type if self.request_type in self.REQUEST_TYPES else self.REQUEST_TYPES[0]

    @property
    def display_request_number(self) -> int:
        return self.request_number or self.id

    @property
    def display_request_type(self) -> str:
        return self.normalized_request_type.title()

    @property
    def request_reference(self) -> str:
        return f"{self.display_request_type} #{self.display_request_number}"

    @property
    def current_appointment(self) -> "Appointment | None":
        return self.appointments[0] if self.appointments else None

    @property
    def derived_status(self) -> str:
        current_appointment = self.current_appointment
        if current_appointment and current_appointment.scheduled_date and current_appointment.status != "Cancelled":
            return "Scheduled"

        quote_decisions = [quote.decision for quote in self.quotes]
        if "Accepted" in quote_decisions:
            return "Accepted"
        if quote_decisions and all(decision == "Rejected" for decision in quote_decisions):
            return "Rejected"
        if quote_decisions:
            return "Quoted"

        # Preserve legacy quoted outcomes until historical data has explicit quote rows.
        if self.status in {"Quoted", "Accepted", "Rejected"}:
            return self.status

        if self.last_contacted_on:
            return "Contacted"
        if self.first_viewed_at:
            return "Viewed"
        return "New"

    def sync_status(self) -> None:
        self.status = self.derived_status


@event.listens_for(QuoteRequest, "before_insert")
def assign_request_number(mapper, connection, target) -> None:
    normalized_request_type = (
        target.request_type if target.request_type in QuoteRequest.REQUEST_TYPES else QuoteRequest.REQUEST_TYPES[0]
    )
    target.request_type = normalized_request_type

    if target.request_number:
        return

    max_request_number = connection.execute(
        select(func.max(QuoteRequest.request_number)).where(QuoteRequest.request_type == normalized_request_type)
    ).scalar_one_or_none()
    target.request_number = (max_request_number or 0) + 1


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=True, index=True)
    recurring_work_id = db.Column(db.Integer, db.ForeignKey("recurring_works.id", ondelete="SET NULL"), nullable=True, index=True)
    title = db.Column(db.String(255), nullable=True)
    scheduled_date = db.Column(db.Date, nullable=True)
    start_time = db.Column(Time, nullable=True)
    end_time = db.Column(Time, nullable=True)
    requested_date = db.Column(db.Date, nullable=True)
    requested_time = db.Column(Time, nullable=True)
    confirmed_date = db.Column(db.Date, nullable=True)
    confirmed_time = db.Column(Time, nullable=True)
    customer_notes = db.Column(db.Text, nullable=True)
    internal_notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="Requested")
    recurring_exception = db.Column(db.Boolean, nullable=False, default=False, server_default=sa.false())
    previous_appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    quote_request = db.relationship("QuoteRequest", back_populates="appointments")
    customer = db.relationship("Customer", back_populates="appointments")
    recurring_work = db.relationship(
        "RecurringWork",
        back_populates="appointments",
        foreign_keys=[recurring_work_id],
    )
    services = db.relationship(
        "ServiceOption",
        secondary=appointment_service_options,
        back_populates="appointments",
        order_by="(ServiceOption.display_order, ServiceOption.name)",
    )
    staff_assignments = db.relationship(
        "AppointmentStaffAssignment",
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="AppointmentStaffAssignment.id",
    )
    assigned_staff = db.relationship(
        "StaffMember",
        secondary="appointment_staff_assignments",
        back_populates="assigned_appointments",
        viewonly=True,
    )
    previous_appointment = db.relationship(
        "Appointment",
        remote_side=[id],
        backref="rescheduled_appointments",
        foreign_keys=[previous_appointment_id],
    )

    @property
    def display_title(self) -> str:
        if self.id is not None:
            return f"Event #{self.id}"
        return "Scheduled event"

    @property
    def is_recurring_sync_locked(self) -> bool:
        return bool(self.recurring_exception or self.status not in APPOINTMENT_STATUSES[:2])

    def __repr__(self) -> str:
        return (
            f"<Appointment {self.id} customer={self.customer_id} request={self.quote_request_id} "
            f"status={self.status} scheduled={self.scheduled_date}>"
        )

class RequestPhoto(db.Model):
    __tablename__ = "request_photos"

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, ForeignKey("quote_requests.id"), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    quote_request = db.relationship("QuoteRequest", back_populates="photos")


class RequestNote(db.Model):
    __tablename__ = "request_notes"

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, ForeignKey("quote_requests.id"), nullable=False, index=True)
    note_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, ForeignKey("users.id"), nullable=False)

    quote_request = db.relationship("QuoteRequest", back_populates="notes")
    author = db.relationship("User", back_populates="notes")


class RequestQuote(db.Model):
    __tablename__ = "request_quotes"

    DECISIONS = REQUEST_QUOTE_DECISIONS
    BILLING_FREQUENCIES = REQUEST_QUOTE_BILLING_FREQUENCIES

    id = db.Column(db.Integer, primary_key=True)
    quote_request_id = db.Column(db.Integer, ForeignKey("quote_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    billing_frequency = db.Column(db.String(16), nullable=True)
    decision = db.Column(db.String(16), nullable=False, default="Sent")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    quote_request = db.relationship("QuoteRequest", back_populates="quotes")

    @property
    def formatted_amount(self) -> str:
        return f"${self.amount:,.2f}"

    def __repr__(self) -> str:
        return (
            f"<RequestQuote {self.id} request={self.quote_request_id} amount={self.amount} "
            f"billing_frequency={self.billing_frequency} decision={self.decision}>"
        )