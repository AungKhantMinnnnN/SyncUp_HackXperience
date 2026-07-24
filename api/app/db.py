"""Async engine, one pool, one session per request. See docs section 4."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.async_database_url,
    pool_size=5,            # Render free = 1 instance; keep small
    max_overflow=5,
    pool_pre_ping=True,     # survive Supabase/Render idle disconnects
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI request-scoped session."""
    async with SessionLocal() as session:
        yield session


async def with_session(fn, *args, **kwargs):
    """Discord/job scope — handlers aren't in a request, so open a session explicitly."""
    async with SessionLocal() as session:
        return await fn(session, *args, **kwargs)
