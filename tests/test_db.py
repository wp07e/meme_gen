"""Tests for the DB layer using an in-memory SQLite engine (isolated per test)."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Job, SeenClip, SessionState


@pytest.fixture
def mem_db():
    """Fresh in-memory DB with tables created; yields the engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_job_create_and_get(mem_db):
    with Session(mem_db) as s:
        s.add(Job(id="job-1", topic="monday", template="caption-top-bottom"))
        s.commit()
    with Session(mem_db) as s:
        job = s.get(Job, "job-1")
        assert job is not None
        assert job.status == "searching"  # default
        assert job.topic == "monday"
        assert job.cancel_requested is False


def test_job_update_status(mem_db):
    with Session(mem_db) as s:
        s.add(Job(id="job-2", topic="x"))
        s.commit()
    with Session(mem_db) as s:
        job = s.get(Job, "job-2")
        job.status = "rendering"
        job.progress_message = "Rendering…"
        s.add(job)
        s.commit()
    with Session(mem_db) as s:
        job = s.get(Job, "job-2")
        assert job.status == "rendering"
        assert job.progress_message == "Rendering…"


def test_job_cancel_flag(mem_db):
    with Session(mem_db) as s:
        s.add(Job(id="job-3", topic="x"))
        s.commit()
    with Session(mem_db) as s:
        job = s.get(Job, "job-3")
        job.cancel_requested = True
        s.add(job)
        s.commit()
    with Session(mem_db) as s:
        assert s.get(Job, "job-3").cancel_requested is True


def test_seen_clip_dedupe_query(mem_db):
    """A clip URL recorded for a session is found by the dedupe query."""
    with Session(mem_db) as s:
        s.add(SeenClip(session_id="sess-1", url="https://x/abc.mp4",
                       source="giphy", query="happy"))
        s.commit()
    with Session(mem_db) as s:
        found = s.exec(
            select(SeenClip).where(
                SeenClip.session_id == "sess-1",
                SeenClip.url == "https://x/abc.mp4",
            )
        ).first()
        assert found is not None
        # Different session: not found
        found2 = s.exec(
            select(SeenClip).where(
                SeenClip.session_id == "sess-2",
                SeenClip.url == "https://x/abc.mp4",
            )
        ).first()
        assert found2 is None


def test_session_state_upsert(mem_db):
    """One row per session, updated in place."""
    with Session(mem_db) as s:
        s.add(SessionState(session_id="sess-1", rotate_index=0, customer_id="cust-1"))
        s.commit()
    with Session(mem_db) as s:
        st = s.get(SessionState, "sess-1")
        st.rotate_index = 1
        s.add(st)
        s.commit()
    with Session(mem_db) as s:
        st = s.get(SessionState, "sess-1")
        assert st.rotate_index == 1
        assert st.customer_id == "cust-1"
