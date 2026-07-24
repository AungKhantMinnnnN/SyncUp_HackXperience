"""0001 core — apply the canonical schema.sql (all tables, extensions, indexes).

down_revision = None. Members B/C add their deltas as 0002/0003 via autogenerate
AFTER this merges (sequence strictly, or you get multiple heads).

We execute schema.sql rather than re-declaring DDL so there is one source of truth
that the Supabase SQL editor and Alembic both apply.
"""

from pathlib import Path

from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "schema.sql"


def upgrade() -> None:
    op.execute(SCHEMA_SQL.read_text())


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
