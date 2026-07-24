"""0003 finance — budgets, event_budgets, budget_line_items, expenses.

Branched from 0002_resources. Creates the four FINANCE tables owned by Member C.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_finance"
down_revision = "0002_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("semester", sa.Text(), nullable=False),
        sa.Column(
            "total_allocated",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "event_budgets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "budget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estimated_total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "actual_total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("stated_cap", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected', 'reconciling', 'closed', 'cancelled')",
            name="event_budgets_status_chk",
        ),
    )

    op.create_table(
        "budget_line_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_budget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "unit_cost",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "line_total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('food', 'venue', 'equipment_rental', 'printing', "
            "'materials', 'transport', 'contingency')",
            name="budget_line_items_category_chk",
        ),
    )

    op.create_table(
        "expenses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_budget_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "paid_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("spent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'disputed', 'rejected', 'reimbursed')",
            name="expenses_status_chk",
        ),
    )


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_table("budget_line_items")
    op.drop_table("event_budgets")
    op.drop_table("budgets")
