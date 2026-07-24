"""FINANCE tables (Member C): budgets, event_budgets, budget_line_items, expenses.

Owner writes the ORM mappings here, mirroring schema.sql. Money is NUMERIC(12,2).
Imported by app/models/__init__ so metadata sees it.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    semester: Mapped[str] = mapped_column(Text, nullable=False)
    total_allocated: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="USD")
    created_at: Mapped[datetime] = created_at()


class EventBudget(Base):
    __tablename__ = "event_budgets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'reconciling', 'closed', 'cancelled')",
            name="event_budgets_status_chk",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )
    estimated_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    actual_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    stated_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = created_at()


class BudgetLineItem(Base):
    __tablename__ = "budget_line_items"
    __table_args__ = (
        CheckConstraint(
            "category IN ('food', 'venue', 'equipment_rental', 'printing', "
            "'materials', 'transport', 'contingency')",
            name="budget_line_items_category_chk",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_budget_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("event_budgets.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'disputed', 'rejected', 'reimbursed')",
            name="expenses_status_chk",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_budget_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("event_budgets.id", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("budget_line_items.id", ondelete="SET NULL")
    )
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("members.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    spent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()