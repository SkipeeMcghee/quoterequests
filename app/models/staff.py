from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Time

from app.extensions import db

staff_service_options = db.Table(
    "staff_service_options",
    db.Column("staff_member_id", db.Integer, db.ForeignKey("staff_members.id", ondelete="CASCADE"), primary_key=True),
    db.Column("service_option_id", db.Integer, db.ForeignKey("service_options.id", ondelete="CASCADE"), primary_key=True),
)


class StaffMember(db.Model):
    __tablename__ = "staff_members"

    COMPENSATION_FREQUENCY_CHOICES = (
        ("hourly", "Hourly"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("biweekly", "Biweekly"),
        ("semimonthly", "Semimonthly"),
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    )

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    role_title = db.Column(db.String(120), nullable=True)
    worker_type = db.Column(db.String(32), nullable=False, default="employee")
    status = db.Column(db.String(32), nullable=False, default="active")
    compensation_amount = db.Column(db.Numeric(10, 2), nullable=True)
    compensation_frequency = db.Column(db.String(24), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    services = db.relationship(
        "ServiceOption",
        secondary="staff_service_options",
        back_populates="staff_members",
        order_by="(ServiceOption.display_order, ServiceOption.name)",
    )
    availability_windows = db.relationship(
        "StaffAvailability",
        back_populates="staff_member",
        cascade="all, delete-orphan",
        order_by="(StaffAvailability.day_of_week, StaffAvailability.start_time)",
    )
    appointment_assignments = db.relationship(
        "AppointmentStaffAssignment",
        back_populates="staff_member",
        cascade="all, delete-orphan",
        order_by="AppointmentStaffAssignment.id",
    )
    assigned_appointments = db.relationship(
        "Appointment",
        secondary="appointment_staff_assignments",
        back_populates="assigned_staff",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<StaffMember {self.id} {self.display_name}>"

    @property
    def compensation_frequency_label(self) -> str | None:
        if not self.compensation_frequency:
            return None

        frequency_labels = dict(self.COMPENSATION_FREQUENCY_CHOICES)
        return frequency_labels.get(self.compensation_frequency, self.compensation_frequency.replace("_", " ").title())


class StaffAvailability(db.Model):
    __tablename__ = "staff_availabilities"

    id = db.Column(db.Integer, primary_key=True)
    staff_member_id = db.Column(db.Integer, db.ForeignKey("staff_members.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = db.Column(db.SmallInteger, nullable=False)
    start_time = db.Column(Time, nullable=False)
    end_time = db.Column(Time, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    staff_member = db.relationship("StaffMember", back_populates="availability_windows")

    def __repr__(self) -> str:
        return (
            f"<StaffAvailability {self.id} staff={self.staff_member_id} day={self.day_of_week} "
            f"{self.start_time}-{self.end_time}>"
        )


class AppointmentStaffAssignment(db.Model):
    __tablename__ = "appointment_staff_assignments"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, index=True)
    staff_member_id = db.Column(db.Integer, db.ForeignKey("staff_members.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_role = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    appointment = db.relationship("Appointment", back_populates="staff_assignments")
    staff_member = db.relationship("StaffMember", back_populates="appointment_assignments")

    def __repr__(self) -> str:
        return f"<AppointmentStaffAssignment {self.id} appointment={self.appointment_id} staff={self.staff_member_id}>"
