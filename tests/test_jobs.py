"""Tests for jobs.py: create/get/cancel + worker lifecycle (done, cancelled, failed)."""
import threading
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.db as db_module
import app.jobs as jobs_module
from app.config import Settings
from app.models import Job, SeenClip, FormatPref, CopyResult, ClipInfo


# Use a shared in-memory DB (file:memdb?mode=memory&cache=shared) so the worker
# thread and the test assertions see the same data.
@pytest.fixture
def shared_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///file:memdb?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(jobs_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    yield test_engine
    test_engine.dispose()


FIXTURE_CLIP = str(__import__("pathlib").Path(__file__).parent / "fixtures" / "test_clip.mp4")


def _clip_info():
    return ClipInfo(path=FIXTURE_CLIP, source="giphy", category="gifs",
                    original_url="https://x/abc.mp4", width=1280, height=720,
                    size_bytes=200_000)


def _copy():
    return CopyResult(caption="cap", hook="hook", overlay_lines=["A", "B"])


def _settings(tmp_path):
    return Settings(giphy_api_key="g", klipy_api_key="k", moonshot_api_key="m",
                    moonshot_model="moonshot-v1-auto",
                    output_dir=str(tmp_path / "out"), tmp_dir=str(tmp_path / "tmp"))


def test_create_and_get_job(shared_db):
    jid = jobs_module.create_job(session_id="s1", topic="monday", template="caption-top-bottom",
                                 format_pref=FormatPref.auto)
    job = jobs_module.get_job(jid)
    assert job is not None
    assert job.status == "searching"
    assert job.topic == "monday"


def test_request_cancel_sets_flag(shared_db):
    jid = jobs_module.create_job(session_id="s1", topic="x", template="t", format_pref=FormatPref.auto)
    assert jobs_module.request_cancel(jid) is True
    job = jobs_module.get_job(jid)
    assert job.cancel_requested is True


def test_request_cancel_missing_job(shared_db):
    assert jobs_module.request_cancel("does-not-exist") is False


def test_worker_completes_done(shared_db, tmp_path, sample_copy):
    """Full happy path: copy provided → clip search → render → done."""
    jid = jobs_module.create_job(session_id="s1", topic="monday", template="caption-top-bottom",
                                 format_pref=FormatPref.auto)
    with patch("app.jobs.fetch_best_clip", return_value=_clip_info()), \
         patch("app.jobs.render_video", return_value=str(tmp_path / "out.mp4")) as mock_render:
        jobs_module.run_render_job(
            job_id=jid, topic="monday", tone="funny",
            template_name="caption-top-bottom", format_pref=FormatPref.auto,
            clip_keyword=None, session_id="s1", settings=_settings(tmp_path),
            copy_result=sample_copy,
        )
    job = jobs_module.get_job(jid)
    assert job.status == "done"
    assert job.result_json is not None
    assert mock_render.called
    # SeenClip recorded for dedupe.
    with Session(shared_db) as s:
        seen = s.exec(__import__("sqlmodel").select(SeenClip)).all()
        assert len(seen) == 1
        assert seen[0].url == "https://x/abc.mp4"


def test_worker_cancelled_during_search(shared_db, tmp_path, sample_copy):
    """If the search loop raises CancelledError, job ends as cancelled."""
    jid = jobs_module.create_job(session_id="s1", topic="monday", template="caption-top-bottom",
                                 format_pref=FormatPref.auto)
    with patch("app.jobs.fetch_best_clip", side_effect=jobs_module.CancelledError()):
        jobs_module.run_render_job(
            job_id=jid, topic="monday", tone="funny",
            template_name="caption-top-bottom", format_pref=FormatPref.auto,
            clip_keyword=None, session_id="s1", settings=_settings(tmp_path),
            copy_result=sample_copy,
        )
    job = jobs_module.get_job(jid)
    assert job.status == "cancelled"
    assert "Cancelled" in job.progress_message


def test_worker_records_failure(shared_db, tmp_path, sample_copy):
    """An unexpected error in render_video lands in status=failed, error set."""
    jid = jobs_module.create_job(session_id="s1", topic="monday", template="caption-top-bottom",
                                 format_pref=FormatPref.auto)
    with patch("app.jobs.fetch_best_clip", return_value=_clip_info()), \
         patch("app.jobs.render_video", side_effect=RuntimeError("encode boom")):
        jobs_module.run_render_job(
            job_id=jid, topic="monday", tone="funny",
            template_name="caption-top-bottom", format_pref=FormatPref.auto,
            clip_keyword=None, session_id="s1", settings=_settings(tmp_path),
            copy_result=sample_copy,
        )
    job = jobs_module.get_job(jid)
    assert job.status == "failed"
    assert "encode boom" in (job.error or "")


def test_worker_runs_in_thread(shared_db, tmp_path, sample_copy):
    """The worker is safe to run in a background thread (the real usage pattern)."""
    jid = jobs_module.create_job(session_id="s1", topic="monday", template="caption-top-bottom",
                                 format_pref=FormatPref.auto)
    with patch("app.jobs.fetch_best_clip", return_value=_clip_info()), \
         patch("app.jobs.render_video", return_value=str(tmp_path / "out.mp4")):
        t = threading.Thread(target=jobs_module.run_render_job, kwargs=dict(
            job_id=jid, topic="monday", tone="funny",
            template_name="caption-top-bottom", format_pref=FormatPref.auto,
            clip_keyword=None, session_id="s1", settings=_settings(tmp_path),
            copy_result=sample_copy,
        ))
        t.start()
        t.join(timeout=30)
    assert not t.is_alive()
    assert jobs_module.get_job(jid).status == "done"
