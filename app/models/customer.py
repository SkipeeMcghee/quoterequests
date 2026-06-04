from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db


class Customer(db.Model):
    __tablename__ = "customers"

    BILLING_FREQUENCIES = ("weekly", "monthly", "per_job")
    DISPLAY_NAME_PREFERENCES = ("individual", "business")

    id = db.Column(db.Integer, primary_key=True)
    primary_name = db.Column(db.String(255), nullable=True)
    individual_name = db.Column(db.String(255), nullable=True)
    business_name = db.Column(db.String(255), nullable=True)
    display_name_preference = db.Column(db.String(16), nullable=True)
    primary_email = db.Column(db.String(255), nullable=True, index=True)
    primary_phone = db.Column(db.String(50), nullable=True, index=True)
    primary_city = db.Column(db.String(255), nullable=True)
    billing_amount = db.Column(db.Numeric(10, 2), nullable=True)
    billing_frequency = db.Column(db.String(16), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    fields = db.relationship(
        "CustomerField",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerField.id",
    )
    notes = db.relationship(
        "CustomerNote",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerNote.created_at.desc()",
    )
    quote_requests = db.relationship(
        "QuoteRequest",
        back_populates="customer",
        order_by="QuoteRequest.created_at.desc()",
    )
    appointments = db.relationship(
        "Appointment",
        back_populates="customer",
        order_by="Appointment.scheduled_date.desc()",
    )
    recurring_works = db.relationship(
        "RecurringWork",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="RecurringWork.starts_on.desc()",
    )
    photos = db.relationship(
        "CustomerPhoto",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerPhoto.created_at.desc()",
    )
    addresses = db.relationship(
        "CustomerAddress",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerAddress.id",
    )

    def __repr__(self) -> str:
        return f"<Customer {self.id} {self.primary_name or 'Unnamed'}>"

    def sync_primary_name(self) -> None:
        cleaned_primary = (self.primary_name or "").strip() or None
        cleaned_individual = (self.individual_name or "").strip() or None
        cleaned_business = (self.business_name or "").strip() or None
        preference = (self.display_name_preference or "").strip().lower() or None

        if preference not in self.DISPLAY_NAME_PREFERENCES:
            preference = None

        if not cleaned_individual and not cleaned_business and cleaned_primary:
            cleaned_individual = cleaned_primary

        if preference == "business" and cleaned_business:
            chosen_name = cleaned_business
        elif preference == "individual" and cleaned_individual:
            chosen_name = cleaned_individual
        elif cleaned_individual:
            preference = "individual"
            chosen_name = cleaned_individual
        elif cleaned_business:
            preference = "business"
            chosen_name = cleaned_business
        else:
            chosen_name = cleaned_primary
            preference = "individual" if chosen_name else None
            cleaned_individual = chosen_name

        self.primary_name = chosen_name
        self.individual_name = cleaned_individual
        self.business_name = cleaned_business
        self.display_name_preference = preference

    @property
    def billing_address(self) -> "CustomerAddress" | None:
        billed = [address for address in self.addresses if address.is_billing]
        if billed:
            return billed[0]
        if len(self.addresses) == 1:
            return self.addresses[0]
        return None

    @property
    def fields_by_kind(self) -> dict[str, list["CustomerField"]]:
        result = {"name": [], "phone": [], "email": [], "city": []}
        for field in self.fields:
            result.setdefault(field.kind, []).append(field)
        return result

    @property
    def display_name_label(self) -> str:
        if self.display_name_preference == "business" and self.business_name:
            return "Business name"
        return "Individual name"

    @property
    def billed_recurring_works(self) -> list["RecurringWork"]:
        return [
            work
            for work in self.recurring_works
            if work.billing_amount is not None and work.billing_frequency
        ]

    @property
    def recurring_billing_total(self) -> Decimal | None:
        billed_works = self.billed_recurring_works
        if not billed_works:
            return None
        return sum((work.billing_amount or Decimal("0.00") for work in billed_works), Decimal("0.00"))

    @property
    def last_activity(self):
        candidates = [qr.created_at for qr in self.quote_requests] + [note.created_at for note in self.notes]
        return max(candidates) if candidates else None


class CustomerField(db.Model):
    __tablename__ = "customer_fields"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(32), nullable=False)
    value = db.Column(db.String(255), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    source_quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", back_populates="fields")

    __table_args__ = (
        db.UniqueConstraint("customer_id", "kind", "value", name="uq_customer_fields_customer_kind_value"),
    )

    def __repr__(self) -> str:
        return f"<CustomerField {self.kind}={self.value} primary={self.is_primary}>"


class CustomerAddress(db.Model):
    __tablename__ = "customer_addresses"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    address_line_1 = db.Column(db.String(255), nullable=True)
    address_line_2 = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(255), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    is_billing = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", back_populates="addresses")

    def __repr__(self) -> str:
        return f"<CustomerAddress {self.id} customer={self.customer_id} billing={self.is_billing}>"


class CustomerNote(db.Model):
    __tablename__ = "customer_notes"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    note_text = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", back_populates="notes")
    author = db.relationship("User")

    def __repr__(self) -> str:
        return f"<CustomerNote customer={self.customer_id} author={self.created_by}>"


class CustomerPhoto(db.Model):
    __tablename__ = "customer_photos"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", back_populates="photos")

    def __repr__(self) -> str:
        return f"<CustomerPhoto {self.id} customer={self.customer_id} file={self.file_path}>"


class RecurringWork(db.Model):
    __tablename__ = "recurring_works"

    FREQUENCIES = ("weekly", "monthly")
    BILLING_FREQUENCIES = Customer.BILLING_FREQUENCIES
    STATUSES = ("active", "inactive")

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_request_id = db.Column(db.Integer, db.ForeignKey("quote_requests.id"), nullable=True, index=True)
    source_appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id", use_alter=True), nullable=True, index=True)
    title = db.Column(db.String(255), nullable=True)
    frequency = db.Column(db.String(16), nullable=False)
    day_of_week = db.Column(db.SmallInteger(), nullable=True)
    day_of_month = db.Column(db.SmallInteger(), nullable=True)
    starts_on = db.Column(db.Date(), nullable=False)
    ends_on = db.Column(db.Date(), nullable=True)
    start_time = db.Column(db.Time(), nullable=True)
    end_time = db.Column(db.Time(), nullable=True)
    billing_amount = db.Column(db.Numeric(10, 2), nullable=True)
    billing_frequency = db.Column(db.String(16), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="active")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    customer = db.relationship("Customer", back_populates="recurring_works")
    quote_request = db.relationship("QuoteRequest")
    appointments = db.relationship(
        "Appointment",
        back_populates="recurring_work",
        foreign_keys="Appointment.recurring_work_id",
        order_by="Appointment.scheduled_date.desc()",
    )

    def __repr__(self) -> str:
        return f"<RecurringWork {self.id} customer={self.customer_id} frequency={self.frequency} starts={self.starts_on}>"
