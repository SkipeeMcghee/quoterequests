from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from app.extensions import db


class GalleryItem(db.Model):
    __tablename__ = "gallery_items"

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(80), nullable=False)
    caption = db.Column(db.String(180), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey("service_options.id", ondelete="SET NULL"), nullable=True, index=True)
    featured = db.Column(db.Boolean, nullable=False, default=False, server_default=sa.false(), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=sa.true(), index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0, server_default="0", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    service = db.relationship("ServiceOption", back_populates="gallery_items")

    @classmethod
    def ordered_query(cls, include_inactive: bool = True):
        query = cls.query.order_by(cls.display_order.asc(), cls.id.asc())
        if not include_inactive:
            query = query.filter(cls.is_active.is_(True))
        return query

    @property
    def normalized_caption(self) -> str | None:
        return (self.caption or "").strip() or None

    @property
    def service_name(self) -> str | None:
        if self.service is None:
            return None
        return self.service.name

    @property
    def alt_text(self) -> str:
        if self.normalized_caption:
            return f"{self.title} - {self.normalized_caption}"
        return self.title