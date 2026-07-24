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
    # asyncpg's SQLAlchemy dialect always prepares a statement before running it, and
    # a prepared statement can't hold more than one SQL command — so a single
    # op.execute() of the whole file fails with "cannot insert multiple commands into
    # a prepared statement" (async engine + asyncpg only; psycopg2 wouldn't hit this).
    # Split on statement-terminating semicolons instead; schema.sql is plain DDL with
    # no string literals or function bodies containing embedded semicolons, so a
    # straight split is safe here — this is not a general-purpose SQL parser.
    for statement in _split_statements(SCHEMA_SQL.read_text()):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")


def _split_statements(sql: str) -> list[str]:
    # Strip `--` line comments first: schema.sql has comments containing semicolons
    # that are not statement terminators (e.g. "must exist before anything below;
    # enable in Supabase SQL editor"). Every `--` in this file is a trailing
    # end-of-line comment, never inside a string literal — verified by inspection,
    # not a general guarantee, so re-check this if schema.sql ever changes shape.
    lines = (line[: line.find("--")] if "--" in line else line for line in sql.splitlines())
    stripped = "\n".join(lines)
    return [statement.strip() for statement in stripped.split(";") if statement.strip()]
