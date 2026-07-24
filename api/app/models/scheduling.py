"""SCHEDULING tables (Member A): busy_blocks, scheduling_requests,
slot_proposals, events, event_attendees.

Mirrors schema.sql (the canonical DDL) — the tables already exist via 0001_core, so
these are ORM mappings only, no new migration. Imported by app/models/__init__.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


class BusyBlock(Base):
    __tablename__ = "busy_blocks"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('class', 'exam', 'work', 'club', 'personal')", name="busy_blocks_kind_chk"
        ),
        CheckConstraint("end_utc > start_utc", name="busy_blocks_time_chk"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    member_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class SchedulingRequest(Base):
    __tablename__ = "scheduling_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('parsing', 'proposing', 'awaiting_choice', "
            "'confirmed', 'expired', 'failed')",
            name="scheduling_requests_status_chk",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("members.id", ondelete="SET NULL")
    )
    raw_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_constraints: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="parsing")
    created_at: Mapped[datetime] = created_at()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'rescheduled', 'completed', 'cancelled')",
            name="events_status_chk",
        ),
        CheckConstraint("end_utc > start_utc", name="events_time_chk"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = _org_fk()
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("members.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_attendance: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = created_at()


class SlotProposal(Base):
    __tablename__ = "slot_proposals"
    __table_args__ = (CheckConstraint("end_utc > start_utc", name="slot_proposals_time_chk"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("scheduling_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL")
    )
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    attendance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    conflicts: Mapped[dict | None] = mapped_column(JSONB)
    rank: Mapped[int | None] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()


class EventAttendee(Base):
    __tablename__ = "event_attendees"

    event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rsvp_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
