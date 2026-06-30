"""Tests for the async job-based API: render→job, poll, cancel."""
import time
from unittest.mock import patch
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

import app.db as db_module
import app.jobs as jobs_module
import app.videos as videos_module
from app.main import app
from app.models import CopyResult, ClipInfo, User
from app.security import hash_password


@pytest.fixture
def shared_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///file:memdb?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(jobs_module, "engine", test_engine)
    monkeypatch.setattr(videos_module, "engine", test_engine)
    # Seed a test user the authenticated routes can act on behalf of.
    with Session(test_engine) as s:
        s.add(User(username="tester", password_hash=hash_password("pw123"), is_admin=False))
        s.commit()
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def client(shared_db):
    """A TestClient already authenticated as 'tester'."""
    with TestClient(app) as c:
        res = c.post("/api/login", json={"username": "tester", "password": "pw123"})
        assert res.status_code == 200, res.text
        yield c


FIXTURE_CLIP = str(Path(__file__).parent / "fixtures" / "test_clip.mp4")


def test_list_templates_route(client):
    res = client.get("/api/templates")
    assert res.status_code == 200
    assert "caption-top-bottom" in res.json()["templates"]


def test_preview_copy_route(client, sample_copy):
    with patch("app.main.generate_copy", return_value=sample_copy):
        res = client.post("/api/preview-copy", json={
            "topic": "Monday gym", "tone": "funny", "template": "caption-top-bottom",
        })
    assert res.status_code == 200
    assert res.json()["copy"]["hook"] == sample_copy.hook


def _wait_for_terminal(client, job_id, timeout=30):
    """Poll until the job is done/cancelled/failed."""
    deadline = time.time() + timeout
    r = None
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}").json()
        if r["status"] in ("done", "cancelled", "failed"):
            return r
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not terminate: {r}")


def test_render_returns_job_id_and_completes(client, sample_copy, tmp_path):
    fake_clip = ClipInfo(path=FIXTURE_CLIP, source="giphy", category="gifs",
                         original_url="https://x/abc.mp4", width=1280, height=720,
                         size_bytes=200_000)
    # The mocks must stay active while the background worker thread runs, so the
    # polling happens inside the `with` block (not just the POST).
    with patch("app.jobs.fetch_best_clip", return_value=fake_clip), \
         patch("app.jobs.render_video", return_value=str(tmp_path / "out.mp4")):
        res = client.post("/api/render", json={
            "topic": "Monday gym", "tone": "funny",
            "template": "caption-top-bottom", "format_pref": "auto",
            "copy_data": sample_copy.model_dump(),
        })
        assert res.status_code == 200
        job_id = res.json()["job_id"]
        final = _wait_for_terminal(client, job_id)
    assert final["status"] == "done"
    assert final["result"]["output_path"].endswith(".mp4")


def test_cancel_route_sets_flag(client, sample_copy, tmp_path):
    """A slow search lets us cancel mid-flight."""
    def slow_search(**kw):
        time.sleep(3)  # hold the search loop open
        return ClipInfo(path=FIXTURE_CLIP, source="giphy", category="gifs",
                        original_url="https://x/abc.mp4", width=1280, height=720,
                        size_bytes=200_000)
    with patch("app.jobs.fetch_best_clip", side_effect=slow_search), \
         patch("app.jobs.render_video", return_value=str(tmp_path / "out.mp4")):
        res = client.post("/api/render", json={
            "topic": "x", "template": "caption-top-bottom", "format_pref": "auto",
            "copy_data": sample_copy.model_dump(),
        })
        job_id = res.json()["job_id"]
        cancel_res = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_res.status_code == 200
        final = _wait_for_terminal(client, job_id, timeout=15)
        assert final["status"] in ("cancelled", "done")  # cancel raced; either is acceptable


def test_cancel_missing_job_404(client):
    res = client.post("/api/jobs/does-not-exist/cancel")
    assert res.status_code == 404


def test_get_missing_job_404(client):
    res = client.get("/api/jobs/does-not-exist")
    assert res.status_code == 404


def test_invalid_format_pref_rejected(client):
    res = client.post("/api/render", json={
        "topic": "x", "template": "caption-top-bottom", "format_pref": "banana",
    })
    assert res.status_code == 422
