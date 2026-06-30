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


# ---- Duration gate in the loop -------------------------------------------

def _hd_klipy_clip(url="https://k/c.mp4"):
    """A Klipy CLIP (category='clips') candidate, HD res, duration unprobed."""
    return ClipInfo(path="", source="klipy", category="clips", original_url=url,
                    width=854, height=480, size_bytes=420_000, duration=None)


def test_loop_probes_and_accepts_clip_in_duration_range(mem_session, tmp_path):
    """A clip-format candidate is probed; if 5-15s it's accepted."""
    probed = []
    def fake_probe(clip):
        probed.append(clip.original_url)
        return clip.model_copy(update={"duration": 8.0})
    with patch("app.clip_source.search_klipy", return_value=[_hd_klipy_clip()]), \
         patch("app.clip_source.search_giphy", return_value=[]), \
         patch("app.clip_source.probe_duration", side_effect=fake_probe), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        clip = fetch_best_clip(
            query="x", format_pref=FormatPref.clip, rotate_start="klipy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=lambda m: None, is_cancelled=lambda: False,
        )
    assert len(probed) == 1          # duration was probed
    assert clip.duration == 8.0


def test_loop_rejects_clip_too_short_after_probe(mem_session, tmp_path):
    """A 3s clip is probed, rejected, and the loop continues (raises after exhausting)."""
    def fake_probe(clip):
        return clip.model_copy(update={"duration": 3.0})  # too short
    with patch("app.clip_source.search_klipy", return_value=[_hd_klipy_clip()]), \
         patch("app.clip_source.search_giphy", return_value=[]), \
         patch("app.clip_source.probe_duration", side_effect=fake_probe):
        with pytest.raises(LookupError):
            fetch_best_clip(
                query="x", format_pref=FormatPref.clip, rotate_start="klipy",
                giphy_key="g", klipy_key="k", klipy_customer_id="c",
                session_id="s1", session=mem_session, dest_dir=str(tmp_path),
                on_attempt=lambda m: None, is_cancelled=lambda: False,
                max_attempts=2,
            )


def test_loop_does_not_probe_gifs(mem_session, tmp_path):
    """GIF-format candidates skip the duration probe entirely (exempt)."""
    probed = []
    with patch("app.clip_source.search_giphy", return_value=[_hd_clip()]), \
         patch("app.clip_source.search_klipy", return_value=[]), \
         patch("app.clip_source.probe_duration", side_effect=lambda c: probed.append(c) or c), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        fetch_best_clip(
            query="x", format_pref=FormatPref.gif, rotate_start="giphy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=lambda m: None, is_cancelled=lambda: False,
        )
    assert probed == []  # GIFs never probed


# ---- format_pref=clip must gate Giphy gif-mp4s too -----------------------
# Regression: Giphy serves everything under category='gifs', so when a user
# picks "clip" the duration gate (keyed on category='clips') was bypassed,
# letting a 1-second gif-mp4 through. With format_pref=clip the 5-15s gate
# applies to ALL candidates, including Giphy gifs.

def test_clip_pref_probes_and_rejects_short_giphy_gif(mem_session, tmp_path):
    """format_pref=clip: a short Giphy gif candidate is probed and rejected."""
    probed = []
    def fake_probe(clip):
        probed.append(clip.original_url)
        return clip.model_copy(update={"duration": 1.0})  # too short
    with patch("app.clip_source.search_giphy", return_value=[_hd_clip(url="https://g/short.mp4")]), \
         patch("app.clip_source.search_klipy", return_value=[]), \
         patch("app.clip_source.probe_duration", side_effect=fake_probe):
        with pytest.raises(LookupError):
            fetch_best_clip(
                query="x", format_pref=FormatPref.clip, rotate_start="giphy",
                giphy_key="g", klipy_key="k", klipy_customer_id="c",
                session_id="s1", session=mem_session, dest_dir=str(tmp_path),
                on_attempt=lambda m: None, is_cancelled=lambda: False,
                max_attempts=2,
            )
    assert probed == ["https://g/short.mp4"]  # was probed despite category='gifs'


def test_clip_pref_accepts_in_range_giphy_gif(mem_session, tmp_path):
    """format_pref=clip: a Giphy gif in 5-15s is accepted after probing."""
    def fake_probe(clip):
        return clip.model_copy(update={"duration": 6.0})
    with patch("app.clip_source.search_giphy", return_value=[_hd_clip(url="https://g/ok.mp4")]), \
         patch("app.clip_source.search_klipy", return_value=[]), \
         patch("app.clip_source.probe_duration", side_effect=fake_probe), \
         patch("app.clip_source.download_clip", side_effect=_mk_download(tmp_path)):
        clip = fetch_best_clip(
            query="x", format_pref=FormatPref.clip, rotate_start="giphy",
            giphy_key="g", klipy_key="k", klipy_customer_id="c",
            session_id="s1", session=mem_session, dest_dir=str(tmp_path),
            on_attempt=lambda m: None, is_cancelled=lambda: False,
        )
    assert clip.duration == 6.0
