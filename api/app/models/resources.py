"""RESOURCES tables (Member B): resources, resource_reservations, packing_list_items.

Owner writes the ORM mappings here, mirroring schema.sql (incl. the btree_gist
exclusion constraint). Imported by app/models/__init__ so metadata sees it.

schema.sql is the DDL of record (0001_core executes it verbatim) — these classes exist
so service.py can query through the ORM; they intentionally do not redeclare the GiST
exclusion constraint, which has no portable SQLAlchemy construct and would just drift
from the real DDL over time.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replacement_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    condition: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class ResourceReservation(Base):
    __tablename__ = "resource_reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('held','confirmed','checked_out','returned','overdue','released')",
            name="resource_reservations_status_chk",
        ),
        CheckConstraint("end_utc > start_utc", name="resource_reservations_time_chk"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    resource_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False
    )
    # References scheduling's `events` table — the real FK constraint lives in schema.sql.
    # No ForeignKey(...) here: resources must never import scheduling's model class
    # (CLAUDE.md's one-way import rule), and models/scheduling.py doesn't exist yet anyway.
    event_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="held")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class PackingListItem(Base):
    __tablename__ = "packing_list_items"
    __table_args__ = (
        CheckConstraint("source IN ('ai','manual')", name="packing_list_items_source_chk"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Same reasoning as ResourceReservation.event_id above — no cross-module ForeignKey.
    event_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resources.id", ondelete="SET NULL")
    )
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    org_owned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="ai")
    est_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = created_at()
