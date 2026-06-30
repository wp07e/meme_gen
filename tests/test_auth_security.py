"""Tests for the auth/security layer and the per-user video library."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

import app.db as db_module
import app.jobs as jobs_module
import app.videos as videos_module
from app.auth import (
    authenticate, create_user, delete_user, list_users,
    seed_admin, set_session_cookie_value,
)
from app.config import Settings
from app.main import app
from app.models import Job, User
from app.security import (
    create_session_cookie, hash_password, parse_session_cookie, verify_password,
)

SECRET = "test-secret-please-do-not-use-in-prod"


@pytest.fixture
def shared_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///file:memdb2?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(jobs_module, "engine", test_engine)
    monkeypatch.setattr(videos_module, "engine", test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def settings(monkeypatch):
    # Set via env so the REAL get_settings() (used by routes) returns our secret
    # everywhere — main.py imported get_settings at module load, so monkeypatching
    # the module attribute wouldn't reach it. Env is the source of truth.
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    return Settings()


@pytest.fixture
def client(shared_db, settings):
    seed_admin(settings)
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #

def test_hash_and_verify_password_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_hash_password_uses_unique_salt():
    assert hash_password("same") != hash_password("same")


def test_verify_password_rejects_malformed_hash():
    assert verify_password("x", "not-a-real-hash") is False
    assert verify_password("x", "") is False


# --------------------------------------------------------------------------- #
# Signed session cookie
# --------------------------------------------------------------------------- #

def test_session_cookie_roundtrip():
    val = create_session_cookie("alice", SECRET)
    assert parse_session_cookie(val, SECRET) == "alice"


def test_session_cookie_rejects_wrong_secret():
    val = create_session_cookie("alice", SECRET)
    assert parse_session_cookie(val, "different-secret") is None


def test_session_cookie_rejects_tampered_value():
    val = create_session_cookie("alice", SECRET)
    tampered = val[:-2] + "XX"
    assert parse_session_cookie(tampered, SECRET) is None


def test_session_cookie_rejects_expired():
    val = create_session_cookie("alice", SECRET, ttl=-10)  # already expired
    assert parse_session_cookie(val, SECRET) is None


def test_session_cookie_rejects_garbage():
    assert parse_session_cookie(None, SECRET) is None
    assert parse_session_cookie("garbage", SECRET) is None
    assert parse_session_cookie("a.b.c.d", SECRET) is None


# --------------------------------------------------------------------------- #
# Admin seeding + user CRUD
# --------------------------------------------------------------------------- #

def test_seed_admin_creates_account(shared_db, settings):
    seed_admin(settings)
    users = list_users()
    assert any(u.username == "testadmin" and u.is_admin for u in users)


def test_seed_admin_idempotent_does_not_repassword(shared_db, settings):
    seed_admin(settings)
    create_user("bob", "original")
    # re-seed should not error and should not touch other users
    seed_admin(settings)
    assert any(u.username == "bob" for u in list_users())


def test_create_user_rejects_duplicate(shared_db, settings):
    seed_admin(settings)
    create_user("bob", "pw1")
    with pytest.raises(ValueError):
        create_user("bob", "pw2")


def test_create_user_rejects_empty(shared_db):
    with pytest.raises(ValueError):
        create_user("", "pw")
    with pytest.raises(ValueError):
        create_user("x", "")


def test_delete_user_protects_seeded_admin(shared_db, settings):
    seed_admin(settings)
    with pytest.raises(ValueError):
        delete_user("testadmin", settings)


def test_delete_user_missing_raises(shared_db, settings):
    with pytest.raises(ValueError):
        delete_user("nobody", settings)


def test_authenticate_verifies_credentials(shared_db, settings):
    seed_admin(settings)
    assert authenticate("testadmin", "testpass123") is not None
    assert authenticate("testadmin", "wrong") is None
    assert authenticate("nope", "x") is None


# --------------------------------------------------------------------------- #
# Login/logout/me over HTTP
# --------------------------------------------------------------------------- #

def test_login_success_sets_cookie(client):
    res = client.post("/api/login", json={"username": "testadmin", "password": "testpass123"})
    assert res.status_code == 200
    assert res.json() == {"username": "testadmin", "is_admin": True}
    assert "meme_gen_auth" in res.cookies


def test_login_bad_credentials(client):
    # Need to drop any cookie from a prior successful login in this session.
    client.cookies.clear()
    res = client.post("/api/login", json={"username": "testadmin", "password": "nope"})
    assert res.status_code == 401
    assert "meme_gen_auth" not in res.cookies


def test_me_requires_auth(client):
    client.cookies.clear()
    res = client.get("/api/me")
    assert res.status_code == 401


def test_protected_route_requires_auth(client):
    client.cookies.clear()
    assert client.get("/api/templates").status_code == 401
    assert client.get("/api/videos").status_code == 401


def test_full_session_lifecycle(client):
    client.cookies.clear()
    client.post("/api/login", json={"username": "testadmin", "password": "testpass123"})
    assert client.get("/api/me").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


# --------------------------------------------------------------------------- #
# Owner-checked file serving
# --------------------------------------------------------------------------- #

def _login_as(client, username, password):
    client.cookies.clear()
    res = client.post("/api/login", json={"username": username, "password": password})
    assert res.status_code == 200


def test_files_endpoint_requires_auth(client):
    client.cookies.clear()
    assert client.get("/api/files/anything.mp4").status_code == 401


def test_files_endpoint_404_for_unowned(shared_db, settings, client, monkeypatch, tmp_path):
    # Seed two users; assign a video to alice; bob must not fetch it.
    create_user("alice", "ap")
    create_user("bob", "bp")
    video = tmp_path / "alice.mp4"
    video.write_bytes(b"fake")

    with Session(shared_db) as s:
        s.add(Job(id="job-alice", status="done", owner_username="alice",
                  output_filename="alice.mp4"))
        s.commit()

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    _login_as(client, "bob", "bp")
    res = client.get("/api/files/alice.mp4")
    assert res.status_code == 404  # owner mismatch -> 404, no existence leak


def test_files_endpoint_404_for_unknown(shared_db, settings, client, monkeypatch, tmp_path):
    create_user("bob", "bp")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _login_as(client, "bob", "bp")
    assert client.get("/api/files/never-existed.mp4").status_code == 404


# --------------------------------------------------------------------------- #
# Per-user video library
# --------------------------------------------------------------------------- #

def _add_done_job(engine, owner, filename="v.mp4", topic="t"):
    with Session(engine) as s:
        s.add(Job(id=f"job-{owner}-{filename}", status="done", owner_username=owner,
                  output_filename=filename, topic=topic))
        s.commit()


def test_videos_list_scoped_to_owner(shared_db, client):
    create_user("alice", "ap")
    create_user("bob", "bp")
    _add_done_job(shared_db, "alice", "a.mp4", topic="Alice's video")
    _add_done_job(shared_db, "bob", "b.mp4", topic="Bob's video")

    _login_as(client, "alice", "ap")
    res = client.get("/api/videos")
    assert res.status_code == 200
    vids = res.json()["videos"]
    assert len(vids) == 1
    assert vids[0]["filename"] == "a.mp4"
    assert vids[0]["url"] == "/api/files/a.mp4"


def test_videos_excludes_anonymous_jobs(shared_db, client):
    create_user("alice", "ap")
    _add_done_job(shared_db, "", "anon.mp4")  # legacy anonymous video, no owner
    _login_as(client, "alice", "ap")
    res = client.get("/api/videos")
    assert res.json()["videos"] == []  # alice doesn't see it


def test_delete_video_removes_row_and_file(shared_db, client, monkeypatch, tmp_path):
    create_user("alice", "ap")
    f = tmp_path / "to-delete.mp4"
    f.write_bytes(b"x")
    _add_done_job(shared_db, "alice", "to-delete.mp4")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    _login_as(client, "alice", "ap")
    res = client.delete("/api/videos/job-alice-to-delete.mp4")
    assert res.status_code == 200
    assert not f.exists()
    with Session(shared_db) as s:
        assert s.get(Job, "job-alice-to-delete.mp4") is None


def test_delete_video_404_for_other_owner(shared_db, client, monkeypatch, tmp_path):
    create_user("alice", "ap")
    create_user("bob", "bp")
    f = tmp_path / "alice2.mp4"
    f.write_bytes(b"x")
    _add_done_job(shared_db, "alice", "alice2.mp4")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    _login_as(client, "bob", "bp")
    res = client.delete("/api/videos/job-alice-alice2.mp4")
    assert res.status_code == 404
    assert f.exists()  # not deleted


def test_bulk_delete_videos(shared_db, client, monkeypatch, tmp_path):
    create_user("alice", "ap")
    for n in ("v1.mp4", "v2.mp4", "v3.mp4"):
        (tmp_path / n).write_bytes(b"x")
        _add_done_job(shared_db, "alice", n)
    _add_done_job(shared_db, "bob", "bob.mp4")  # not alice's; should be skipped
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    _login_as(client, "alice", "ap")
    res = client.post("/api/videos/bulk-delete", json={
        "job_ids": ["job-alice-v1.mp4", "job-alice-v2.mp4", "job-bob-bob.mp4"]
    })
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] == 2
    assert "job-bob-bob.mp4" in body["skipped"]
    assert not (tmp_path / "v1.mp4").exists()
    assert (tmp_path / "v3.mp4").exists()  # untouched


# --------------------------------------------------------------------------- #
# Admin endpoints
# --------------------------------------------------------------------------- #

def test_admin_endpoints_require_admin(shared_db, client):
    create_user("worker", "wp")
    _login_as(client, "worker", "wp")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users",
                       json={"username": "x", "password": "y"}).status_code == 403


def test_admin_can_create_and_delete_user(shared_db, client):
    _login_as(client, "testadmin", "testpass123")
    res = client.post("/api/admin/users", json={"username": "newperson", "password": "pw"})
    assert res.status_code == 200
    names = {u["username"] for u in client.get("/api/admin/users").json()["users"]}
    assert "newperson" in names

    res = client.delete("/api/admin/users/newperson")
    assert res.status_code == 200
    names = {u["username"] for u in client.get("/api/admin/users").json()["users"]}
    assert "newperson" not in names


def test_admin_cannot_delete_seeded_admin(shared_db, client):
    _login_as(client, "testadmin", "testpass123")
    res = client.delete("/api/admin/users/testadmin")
    assert res.status_code == 400


def test_admin_create_duplicate_returns_409(shared_db, client):
    _login_as(client, "testadmin", "testpass123")
    client.post("/api/admin/users", json={"username": "dup", "password": "pw"})
    res = client.post("/api/admin/users", json={"username": "dup", "password": "pw"})
    assert res.status_code == 409
