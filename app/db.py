"""SQLite persistence via SQLModel.

A file at meme_gen.db (gitignored). WAL mode + busy_timeout let multiple
gunicorn worker processes share the same DB file safely: readers never block
writers, and a concurrent write waits (up to busy_timeout) instead of raising
"database is locked". This supports the multi-worker production deploy behind
nginx. To migrate to Postgres for heavier scale, swap DATABASE_URL.
"""
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///meme_gen.db")

# check_same_thread=False: worker threads (jobs.py) share the engine within a
# process. The connect listener below extends safety to multiple *processes*.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _conn_record) -> None:
    """Apply WAL + concurrency pragmas to every new SQLite connection.

    - journal_mode=WAL: readers don't block writers across processes, so N
      gunicorn workers can read job state while another renders/writes.
    - busy_timeout=5000: a contended write waits up to 5s rather than failing
      instantly with "database is locked".
    - synchronous=NORMAL: safe under WAL and faster than the FULL default.
    foreign_keys=ON is also enforced so ON DELETE CASCADE rules hold.

    No-op for non-SQLite engines (e.g. Postgres): the pragma calls would error,
    so we guard by inspecting the connection's DBAPI module name.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def init_db() -> None:
    """Create all tables. Idempotent. Called on FastAPI startup."""
    # Import here so SQLModel.metadata sees all table models before create_all.
    import app.models  # noqa: F401  (registers tables)
    SQLModel.metadata.create_all(engine)


def _table_columns(table_name: str) -> set[str]:
    """Return the column names of a table (SQLite introspection)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {r[1] for r in rows}


def run_migrations() -> None:
    """Idempotently add columns the multi-user/auth work introduced.

    SQLModel.metadata.create_all() only creates *missing tables*; it will not
    ALTER an existing table to add new columns. So for the live DB we add the
    job.owner_username / job.output_filename columns here if absent, then
    backfill output_filename for legacy done rows that only have result_json.
    """
    from sqlalchemy import text

    cols = _table_columns("job")
    stmts: list[str] = []
    if "owner_username" not in cols:
        stmts.append("ALTER TABLE job ADD COLUMN owner_username VARCHAR DEFAULT ''")
    if "output_filename" not in cols:
        stmts.append("ALTER TABLE job ADD COLUMN output_filename VARCHAR DEFAULT ''")
    if stmts:
        with engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))

    # Backfill: legacy done rows carry the path only inside result_json.
    import json
    import app.models  # noqa: F401
    from app.models import Job
    with Session(engine) as s:
        rows = s.exec(
            select(Job).where(Job.output_filename == "").where(Job.result_json.isnot(None))  # type: ignore[union-attr]
        ).all()
        for job in rows:
            try:
                path = json.loads(job.result_json).get("output_path", "")
            except Exception:
                continue
            fname = path.rsplit("/", 1)[-1] if path else ""
            if fname:
                job.output_filename = fname
                s.add(job)
        s.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a short-lived Session; commit on success, rollback on error.

    expire_on_commit=False so callers may read attributes off returned ORM
    objects after the context closes (we don't rely on SQLAlchemy's
    auto-refresh-on-access behavior)."""
    session = Session(engine, expire_on_commit=False)
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
