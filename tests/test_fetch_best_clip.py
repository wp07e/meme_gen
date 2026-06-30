"""Tests for fetch_best_clip: rotation, dedupe, quality gate, mutation, cancel."""
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.clip_source import fetch_best_clip, CancelledError
from app.models import ClipInfo, FormatPref, SeenClip


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    yield s
    s.close()


def _hd_clip(source="giphy", url="https://x/a.mp4"):
    return ClipInfo(path="", source=source, category="gifs", original_url=url,
                    width=1280, height=720, size_bytes=200_000)


def _low_clip(source="giphy", url="https://x/b.mp4"):
    return ClipInfo(path="", source=source, category="gifs", original_url=url,
                    width=320, height=180, size_bytes=10_000)


def _mk_download(dest_dir):
    """Mock download_clip that doesn't hit the network — just stamps a path."""
    def _dl(*, clip, dest_dir):
        return clip.model_copy(update={"path": f"{dest_dir}/fake.mp4"})
    return _dl


def test_accepts_first_good_clip(mem_session, tmp_path):
    progress = []
    with patch("app.clip_source.search_giphy", return_value=[_hd_clip()]), \
         patch("app.clip_source.search_klipy", return_value=[]), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        clip = fetch_best_clip(
            query="happy", format_pref=FormatPref.auto, rotate_start="giphy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=progress.append, is_cancelled=lambda: False,
        )
    assert clip.short_edge >= 480
    assert any("accepted" in p for p in progress)


def test_rejects_low_quality_then_accepts_hd(mem_session, tmp_path):
    """First candidate is low quality, second is good — loop must skip then accept."""
    candidates = [_low_clip(url="low"), _hd_clip(url="good")]
    progress = []
    with patch("app.clip_source.search_giphy", return_value=candidates), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        clip = fetch_best_clip(
            query="happy", format_pref=FormatPref.auto, rotate_start="giphy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=progress.append, is_cancelled=lambda: False,
        )
    assert clip.original_url == "good"
    assert any("low quality" in p for p in progress)


def test_dedupe_skips_seen_clip(mem_session, tmp_path):
    """A clip URL already in SeenClip for this session is skipped."""
    mem_session.add(SeenClip(session_id="s1", url="https://x/seen.mp4", source="giphy"))
    mem_session.commit()
    seen = _hd_clip(url="https://x/seen.mp4")
    fresh = _hd_clip(url="https://x/fresh.mp4")
    progress = []
    with patch("app.clip_source.search_giphy", return_value=[seen, fresh]), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        clip = fetch_best_clip(
            query="happy", format_pref=FormatPref.auto, rotate_start="giphy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=progress.append, is_cancelled=lambda: False,
        )
    assert clip.original_url == "https://x/fresh.mp4"
    assert any("already used" in p for p in progress)


def test_cancel_aborts_loop(mem_session, tmp_path):
    """If is_cancelled returns True, the loop raises CancelledError."""
    call_count = {"n": 0}
    def is_cancelled():
        call_count["n"] += 1
        return call_count["n"] > 1  # cancel almost immediately
    with patch("app.clip_source.search_giphy", return_value=[_hd_clip()]):
        with pytest.raises(CancelledError):
            fetch_best_clip(
                query="x", format_pref=FormatPref.auto, rotate_start="giphy",
                giphy_key="g", klipy_key="k", klipy_customer_id="c",
                session_id="s1", session=mem_session, dest_dir=str(tmp_path),
                on_attempt=lambda m: None, is_cancelled=is_cancelled,
            )


def test_query_mutation_drops_trailing_words(mem_session, tmp_path):
    """After exhausting providers for a query, trailing words are dropped."""
    queries_seen = []
    def fake_search(*, query, **kw):
        queries_seen.append(query)
        return []  # never return anything → forces mutation
    with patch("app.clip_source.search_giphy", side_effect=fake_search), \
         patch("app.clip_source.search_klipy", side_effect=fake_search):
        with pytest.raises(LookupError):
            fetch_best_clip(
                query="monday motivation gym", format_pref=FormatPref.gif,
                rotate_start="giphy",
                giphy_key="g", klipy_key="k", klipy_customer_id="c",
                session_id="s1", session=mem_session, dest_dir=str(tmp_path),
                on_attempt=lambda m: None, is_cancelled=lambda: False,
                max_attempts=4,
            )
    # Should have tried progressively shorter queries.
    assert "monday motivation gym" in queries_seen
    assert any(q == "monday motivation" for q in queries_seen)


def test_rotation_starts_with_klipy_when_requested(mem_session, tmp_path):
    """rotate_start='klipy' means Klipy is searched before Giphy."""
    provider_order = []
    def fake_klipy(*, query, **kw):
        provider_order.append("klipy")
        return [_hd_clip(source="klipy", url="https://k/clip.mp4")]
    def fake_giphy(*, query, **kw):
        provider_order.append("giphy")
        return []
    with patch("app.clip_source.search_klipy", side_effect=fake_klipy), \
         patch("app.clip_source.search_giphy", side_effect=fake_giphy), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        fetch_best_clip(
            query="happy", format_pref=FormatPref.auto, rotate_start="klipy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=lambda m: None, is_cancelled=lambda: False,
        )
    assert provider_order[0] == "klipy"
