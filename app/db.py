"""SQLite persistence via SQLModel.

Local single-user: a file at meme_gen.db (gitignored). To migrate to Postgres
for a multi-user/web deploy, swap DATABASE_URL and drop check_same_thread.
"""
import os
from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///meme_gen.db")

# check_same_thread=False: worker threads (jobs.py) share the engine.
# SQLite handles concurrent reads; writes serialize — fine for local single-user.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)


def init_db() -> None:
    """Create all tables. Idempotent. Called on FastAPI startup."""
    # Import here so SQLModel.metadata sees all table models before create_all.
    import app.models  # noqa: F401  (registers tables)
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a short-lived Session; commit on success, rollback on error."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a raw Session (caller manages commit/close). For worker threads."""
    return Session(engine)
