"""Database engine and transactions. Services query through SQLAlchemy directly; there is no repository layer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import NullPool, event, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from . import config

_sessions: async_sessionmaker[AsyncSession] | None = None


def configure(url: str, pooled: bool = True) -> None:
    """pooled=False: a fresh connection per transaction (tests, where the app and the test run on different loops)."""
    global _sessions
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add the Supabase Session pooler URL to .env")
    opts: dict = {}
    if make_url(url).get_backend_name() == "postgresql" and pooled:
        # Free Supabase pooler allows few client connections: keep the pool small and recycle idle ones. No pre-ping:
        # it costs a full round trip to the database on every request; recycling covers connections the pooler drops.
        opts = {"pool_size": 3, "max_overflow": 2, "pool_recycle": 120}
        if make_url(url).port == 6543:  # transaction pooler: no prepared statements across connections
            opts["connect_args"] = {"statement_cache_size": 0}
    else:
        opts = {"poolclass": NullPool}  # SQLite in tests: a fresh connection per transaction, safe across loops
    engine = create_async_engine(url, **opts)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless each connection turns them on.
        event.listen(engine.sync_engine, "connect", lambda conn, _: conn.execute("pragma foreign_keys=on"))
    _sessions = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """One unit of work: commits on success, rolls back on any error."""
    if _sessions is None:
        configure(config.DATABASE_URL)
    async with _sessions() as s, s.begin():
        yield s
