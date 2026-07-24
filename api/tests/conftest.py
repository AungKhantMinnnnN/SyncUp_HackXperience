"""Shared test fixtures.

Uses a dedicated local Postgres database (syncup_test) — fully separate from the
seeded dev/demo database (syncup_dev), so running the suite never disturbs demo data.
service.py's functions only ever take an AsyncSession, so tests build their own
engine/session here rather than touching app.db's module-level engine (which is bound
to whatever DATABASE_URL is in .env for local dev).

The engine is created fresh per test (function-scoped), not once at module level:
pytest-asyncio gives each test its own event loop by default, and asyncpg connections
are bound to the loop they were created under, so a module-level engine shared across
tests breaks the moment a second test tries to reuse a pooled connection from the
first test's now-closed loop ("cannot perform operation: another operation is in
progress" / "attached to a different loop").

Requires: a local Postgres reachable at postgresql+asyncpg://postgres@localhost:5433/
syncup_test with schema.sql already applied. Tests that need it are skipped with a
clear reason if the database isn't reachable, so `pytest` still runs the pure unit
tests (availability, state machine, catalogue matching, agent schemas) anywhere.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "postgresql+asyncpg://postgres@localhost:5433/syncup_test"


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except OperationalError:
        await engine.dispose()
        pytest.skip(f"no Postgres reachable at {TEST_DATABASE_URL} — start the local test DB to run this test")

    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as session:
        # TRUNCATE ... CASCADE follows FK dependencies transitively regardless of
        # declared ON DELETE actions, so truncating these two pulls in every table
        # that (directly or indirectly) references them — a clean slate per test.
        await session.execute(text("TRUNCATE organizations, events RESTART IDENTITY CASCADE"))
        await session.commit()
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def org_id(db: AsyncSession) -> uuid.UUID:
    result = await db.execute(text("INSERT INTO organizations (name) VALUES ('Test Org') RETURNING id"))
    oid = result.scalar_one()
    await db.commit()
    return oid
