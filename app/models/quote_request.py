from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Time

from app.extensions import db


QUOTE_REQUEST_STATUSES = ("New", "Contacted", "Quoted", "Won", "Lost")
REQUEST_TYPES = ("Quote request", "Work request")

APPOINTMENT_STATUSES = ("Requested", "Scheduled", "Completed", "Cancelled", "Rescheduled", "No Show")

quote_request_service_options = db.Table(
    "quote_request_service_options",
    db.Column("quote_request_id", db.Integer, db.ForeignKey("quote_requests.id"), primary_key=True),
    db.Column("service_option_id", db.Integer, db.ForeignKey("service_options.id"), primary_key=True),
)


class ServiceOption(db.Model):
    __tablename__ = "service_options"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)

    quote_requests = db.relationship(
        "QuoteRequest",
        secondary=quote_request_service_options,
        back_populates="services",
        order_by="QuoteRequest.id",
    )

    def __str__(self) -> str:
        return self.name

    @classmethod
    def default_service_names(cls) -> list[str]:
        return [
            "Landscape Design",
            "Roof Repair",
            "Window Cleaning",
            "Inspection",
            "Painting",
            "Deck Staining",
            "Flooring",
            "Siding",
            "Fence Repair",
            "General Maintenance",
        ]


class QuoteRequest(db.Model):
    __tablename__ = "quote_requests"
    REQUEST_TYPES = ("Quote request", "Work request")

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    city = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="New")
    request_type = db.Column(db.String(32), nullable=False, default="Quote request")
    additional_notes = db.Column(db.Text, nullable=True)
    last_contacted_on = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)

    services = db.relationship(
        "ServiceOption",
        secondary=quote_request_service_options,
        back_populates="quote_requests",
        order_by="ServiceOption.name",
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
    customer = db.relationship("Customer", back_populates="quote_requests")

    @property
    def service_list_display(self) -> str:
        return ", ".join([service.name for service in self.services])

    @property
    def current_appointment(self) -> "Appointment | None":
        return self.appointments[0] if self.appointments else None


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
    requested_time_window = db.Column(db.String(120), nullable=True)
    confirmed_date = db.Column(db.Date, nullable=True)
    confirmed_time_window = db.Column(db.String(120), nullable=True)
    customer_notes = db.Column(db.Text, nullable=True)
    internal_notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="Requested")
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
    previous_appointment = db.relationship(
        "Appointment",
        remote_side=[id],
        backref="rescheduled_appointments",
        foreign_keys=[previous_appointment_id],
    )

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.quote_request and self.quote_request.full_name:
            return f"Appointment for {self.quote_request.full_name}"
        if self.customer and self.customer.primary_name:
            return f"Appointment for {self.customer.primary_name}"
        return "Scheduled work"

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