"""Tests for per-user asset bundles and their use in the render path."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import SQLModel, Session, create_engine

import app.db as db_module
import app.jobs as jobs_module
import app.videos as videos_module
import app.bundles as bundles_module
from app.auth import create_user, seed_admin
from app.bundles import BundleError, bundle_assets_dir, create_bundle, delete_bundle, list_bundles
from app.config import Settings
from app.main import app
from app.security import hash_password

SECRET = "test-secret-bundles"
FIXTURE_CLIP = str(Path(__file__).parent / "fixtures" / "test_clip.mp4")


def _png_bytes(size=(240, 70), color=(0, 0, 0, 120)) -> bytes:
    """A real PNG file's bytes (so the magic-byte check passes)."""
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _png_file(size=(240, 70)):
    return _png_bytes(size).getvalue()


@pytest.fixture
def shared_db(monkeypatch):
    test_engine = create_engine(
        "sqlite:///file:bundledb?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(jobs_module, "engine", test_engine)
    monkeypatch.setattr(videos_module, "engine", test_engine)
    monkeypatch.setattr(bundles_module, "engine", test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("ADMIN_USERNAME", "testadmin")
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    return Settings()


@pytest.fixture
def client(shared_db, settings, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "up"))
    seed_admin(settings)
    create_user("alice", "ap")
    create_user("bob", "bp")
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    client.cookies.clear()
    res = client.post("/api/login", json={"username": username, "password": password})
    assert res.status_code == 200


# --------------------------------------------------------------------------- #
# Bundle CRUD (direct functions)
# --------------------------------------------------------------------------- #

def _fake_upload(data: bytes):
    """A minimal stand-in for starlette's UploadFile — only .file.read() is used."""
    class _F:
        def __init__(self, d): self._d = d
        def read(self): return self._d
    class _U:
        def __init__(self, d): self.file = _F(d)
    return _U(data)


def test_create_bundle_writes_named_pngs(shared_db, tmp_path):
    up = str(tmp_path / "up")
    b = create_bundle(owner_username="alice", name="Kit A",
                      bottom_bar=_fake_upload(_png_file((1080, 160))),
                      watermark=_fake_upload(_png_file((240, 70))),
                      uploads_dir=up)
    assert b.name == "Kit A"
    d = Path(up) / "alice" / b.bundle_id
    assert (d / "bottom-bar.png").exists()
    assert (d / "watermark.png").exists()
    assert bundle_assets_dir(b.bundle_id, "alice", up) == d


def test_create_bundle_rejects_non_png(shared_db, tmp_path):
    up = str(tmp_path / "up")
    with pytest.raises(BundleError):
        create_bundle(owner_username="alice", name="x",
                      bottom_bar=_fake_upload(b"not a png"),
                      watermark=_fake_upload(_png_file()),
                      uploads_dir=up)


def test_create_bundle_rejects_missing_slot(shared_db, tmp_path):
    up = str(tmp_path / "up")
    with pytest.raises(BundleError):
        create_bundle(owner_username="alice", name="x",
                      bottom_bar=_fake_upload(b""),
                      watermark=_fake_upload(_png_file()),
                      uploads_dir=up)


def test_list_bundles_scoped_to_owner(shared_db, tmp_path):
    up = str(tmp_path / "up")
    create_bundle(owner_username="alice", name="alice kit",
                  bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                  uploads_dir=up)
    create_bundle(owner_username="bob", name="bob kit",
                  bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                  uploads_dir=up)
    assert {b.name for b in list_bundles("alice")} == {"alice kit"}
    assert {b.name for b in list_bundles("bob")} == {"bob kit"}


def test_delete_bundle_removes_row_and_dir(shared_db, tmp_path):
    up = str(tmp_path / "up")
    b = create_bundle(owner_username="alice", name="k",
                      bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                      uploads_dir=up)
    d = bundle_assets_dir(b.bundle_id, "alice", up)
    assert delete_bundle(b.bundle_id, "alice", up) is True
    assert not d.exists()
    assert list_bundles("alice") == []


def test_delete_bundle_unowned_returns_false(shared_db, tmp_path):
    up = str(tmp_path / "up")
    b = create_bundle(owner_username="alice", name="k",
                      bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                      uploads_dir=up)
    # bob can't delete alice's bundle
    assert delete_bundle(b.bundle_id, "bob", up) is False
    assert bundle_assets_dir(b.bundle_id, "alice", up) is not None  # still there


def test_bundle_assets_dir_unowned_is_none(shared_db, tmp_path):
    up = str(tmp_path / "up")
    b = create_bundle(owner_username="alice", name="k",
                      bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                      uploads_dir=up)
    assert bundle_assets_dir(b.bundle_id, "bob", up) is None
    assert bundle_assets_dir("no-such-id", "alice", up) is None


# --------------------------------------------------------------------------- #
# Bundle HTTP endpoints
# --------------------------------------------------------------------------- #

def test_list_bundles_endpoint_requires_auth(client):
    client.cookies.clear()
    assert client.get("/api/bundles").status_code == 401


def test_create_bundle_endpoint(shared_db, client, tmp_path):
    _login(client, "alice", "ap")
    res = client.post("/api/bundles",
                      data={"name": "HTTP kit"},
                      files={"bottom_bar": ("b.png", _png_bytes((1080, 160)), "image/png"),
                             "watermark": ("w.png", _png_bytes((240, 70)), "image/png")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "HTTP kit"
    bid = body["bundle_id"]
    # appears in the owner's list
    names = {b["name"] for b in client.get("/api/bundles").json()["bundles"]}
    assert "HTTP kit" in names
    # file written under uploads/<owner>/<id>/
    assert (tmp_path / "up" / "alice" / bid / "bottom-bar.png").exists()


def test_create_bundle_endpoint_rejects_non_png(shared_db, client):
    _login(client, "alice", "ap")
    res = client.post("/api/bundles",
                      data={"name": "bad"},
                      files={"bottom_bar": ("b.png", b"not a png", "image/png"),
                             "watermark": ("w.png", _png_bytes(), "image/png")})
    assert res.status_code == 400


def test_delete_bundle_endpoint(shared_db, client):
    _login(client, "alice", "ap")
    created = client.post("/api/bundles",
                          data={"name": "to del"},
                          files={"bottom_bar": ("b.png", _png_bytes(), "image/png"),
                                 "watermark": ("w.png", _png_bytes(), "image/png")}).json()
    res = client.delete(f"/api/bundles/{created['bundle_id']}")
    assert res.status_code == 200
    assert client.get("/api/bundles").json()["bundles"] == []


def test_delete_bundle_endpoint_unowned_404(shared_db, client):
    # alice creates; bob can't delete it.
    _login(client, "alice", "ap")
    created = client.post("/api/bundles",
                          data={"name": "alice's"},
                          files={"bottom_bar": ("b.png", _png_bytes(), "image/png"),
                                 "watermark": ("w.png", _png_bytes(), "image/png")}).json()
    _login(client, "bob", "bp")
    assert client.delete(f"/api/bundles/{created['bundle_id']}").status_code == 404


def test_bundles_isolated_per_user(shared_db, client):
    _login(client, "alice", "ap")
    client.post("/api/bundles", data={"name": "alice kit"},
                files={"bottom_bar": ("b.png", _png_bytes(), "image/png"),
                       "watermark": ("w.png", _png_bytes(), "image/png")})
    _login(client, "bob", "bp")
    assert client.get("/api/bundles").json()["bundles"] == []


# --------------------------------------------------------------------------- #
# Render path uses the bundle's assets dir
# --------------------------------------------------------------------------- #

def test_resolve_assets_dir_random_picks_owned(shared_db, settings, tmp_path):
    from app.jobs import _resolve_assets_dir
    up = str(tmp_path / "up")
    settings = Settings(secret_key=SECRET, uploads_dir=up)
    b1 = create_bundle(owner_username="alice", name="k1",
                       bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                       uploads_dir=up)
    b2 = create_bundle(owner_username="alice", name="k2",
                       bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                       uploads_dir=up)
    valid_ids = {b1.bundle_id, b2.bundle_id}
    d = _resolve_assets_dir("random", "alice", settings)
    assert d is not None and d.exists()
    assert d.name in valid_ids  # it's one of alice's bundle dirs
    assert (d / "bottom-bar.png").exists()


def test_resolve_assets_dir_random_no_bundles_returns_none(shared_db, settings, tmp_path):
    from app.jobs import _resolve_assets_dir
    settings = Settings(secret_key=SECRET, uploads_dir=str(tmp_path / "up"))
    assert _resolve_assets_dir("random", "alice", settings) is None


def test_resolve_assets_dir_unowned_returns_none(shared_db, settings, tmp_path):
    from app.jobs import _resolve_assets_dir
    settings = Settings(secret_key=SECRET, uploads_dir=str(tmp_path / "up"))
    b = create_bundle(owner_username="alice", name="k",
                      bottom_bar=_fake_upload(_png_file()), watermark=_fake_upload(_png_file()),
                      uploads_dir=str(tmp_path / "up"))
    # bob asks for alice's bundle -> None (falls back to defaults)
    assert _resolve_assets_dir(b.bundle_id, "bob", settings) is None
