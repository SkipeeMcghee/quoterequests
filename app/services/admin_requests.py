from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models import QuoteRequest, RequestNote, User


def list_quote_requests() -> list[QuoteRequest]:
    statement = select(QuoteRequest).order_by(QuoteRequest.created_at.desc())
    return list(db.session.scalars(statement))


def get_quote_request(request_id: int) -> QuoteRequest:
    statement = (
        select(QuoteRequest)
        .where(QuoteRequest.id == request_id)
        .options(selectinload(QuoteRequest.photos), selectinload(QuoteRequest.notes).selectinload(RequestNote.author))
    )
    quote_request = db.session.scalar(statement)
    if quote_request is None:
        raise NotFound("Quote request not found.")
    return quote_request


def update_request_status(request_id: int, status: str) -> QuoteRequest:
    quote_request = get_quote_request(request_id)
    quote_request.status = status
    db.session.commit()
    return quote_request


def add_request_note(request_id: int, note_text: str, user: User) -> RequestNote:
    quote_request = get_quote_request(request_id)
    note = RequestNote(note_text=note_text.strip(), author=user)
    quote_request.notes.append(note)
    db.session.commit()
    return note