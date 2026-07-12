"""SQLite engine + session. WAL mode on every connection."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# NullPool: local SQLite connections are ~free, and the default QueuePool
# (5 + 10 overflow) deadlocks a 20-way concurrent /run burst — each request
# holds its Session connection across the await on the upstream HTTP fetch.
engine = create_engine(
    _settings.api_h_database_url,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create data/ dir (for file-backed SQLite) and all tables."""
    from app import models  # noqa: F401  (register mappings)

    url = _settings.api_h_database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        path = url.removeprefix("sqlite:///")
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    Base.metadata.create_all(engine)
