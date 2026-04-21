from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey

from app.extensions import db


QUOTE_REQUEST_STATUSES = ("New", "Contacted", "Quoted", "Won", "Lost")


class QuoteRequest(db.Model):
    __tablename__ = "quote_requests"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    service_type = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    preferred_contact_method = db.Column(db.String(50), nullable=False)
    preferred_contact_time = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="New")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

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