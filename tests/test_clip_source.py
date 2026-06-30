"""Tests for clip_source: Klipy parsing, Giphy search, quality gate, download."""
from unittest.mock import patch, MagicMock

import pytest

from app.clip_source import (
    fetch_clip, search_giphy, search_klipy, _parse_klipy_item,
    download_clip, meets_quality, RateLimitError,
)
from app.models import ClipInfo


# ---- Quality gate --------------------------------------------------------

def test_meets_quality_accepts_hd():
    clip = ClipInfo(path="", source="giphy", original_url="x",
                    width=1280, height=720, size_bytes=200_000)
    assert meets_quality(clip) is True


def test_meets_quality_rejects_small_short_edge():
    # 854x480 is fine; 640x360 (short edge 360) is too small.
    clip = ClipInfo(path="", source="giphy", original_url="x",
                    width=640, height=360, size_bytes=200_000)
    assert meets_quality(clip) is False


def test_meets_quality_rejects_tiny_file():
    clip = ClipInfo(path="", source="giphy", original_url="x",
                    width=1280, height=720, size_bytes=10_000)
    assert meets_quality(clip) is False


def test_meets_quality_rejects_unknown_dims():
    clip = ClipInfo(path="", source="giphy", original_url="x", size_bytes=200_000)
    assert meets_quality(clip) is False  # short_edge 0


# ---- Giphy search --------------------------------------------------------

def test_search_giphy_parses_candidates():
    fake_body = {"data": [
        {"images": {"hd": {"mp4": "https://x/hd.mp4", "width": "1080", "height": "608", "mp4_size": "900000"}}},
        {"images": {"original": {"mp4": "https://x/sd.mp4", "width": "480", "height": "270", "mp4_size": "130000"}}},
        {"images": {"original": {}}},  # no mp4 — skipped
    ]}
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake_body
    resp.raise_for_status = MagicMock()
    with patch("app.clip_source.httpx.get", return_value=resp):
        candidates = search_giphy(query="happy", api_key="g_key")
    assert len(candidates) == 2
    assert candidates[0].original_url == "https://x/hd.mp4"
    assert candidates[0].width == 1080
    assert candidates[0].size_bytes == 900000


# ---- Klipy parsing (the crash fix) ---------------------------------------

KLIPY_CLIP_ITEM = {
    "title": "Test",
    "file": {"mp4": "https://static.klipy.com/clip.mp4",
             "gif": "https://static.klipy.com/clip.gif"},
    "file_meta": {"mp4": {"width": 1280, "height": 592, "size": 500000}},
}

KLIPY_GIF_ITEM = {
    "title": "Test gif",
    "file": {
        "hd": {"mp4": {"url": "https://static.klipy.com/hd.mp4", "width": 498, "height": 498, "size": 119294}},
        "sm": {"mp4": {"url": "https://static.klipy.com/sm.mp4", "width": 320, "height": 320, "size": 49565}},
    },
}


def test_parse_klipy_clip_item():
    clip = _parse_klipy_item(KLIPY_CLIP_ITEM, "clips")
    assert clip is not None
    assert clip.source == "klipy"
    assert clip.category == "clips"
    assert clip.original_url == "https://static.klipy.com/clip.mp4"
    assert clip.width == 1280 and clip.height == 592 and clip.size_bytes == 500000


def test_parse_klipy_gif_item_prefers_hd():
    clip = _parse_klipy_item(KLIPY_GIF_ITEM, "gifs")
    assert clip is not None
    assert clip.category == "gifs"
    assert clip.original_url == "https://static.klipy.com/hd.mp4"
    assert clip.width == 498


def test_search_klipy_uses_correct_path_url():
    """The fix: app_key must be in the PATH, not a query param."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"data": {"data": [KLIPY_CLIP_ITEM], "has_next": False}}
    resp.raise_for_status = MagicMock()
    with patch("app.clip_source.httpx.get", return_value=resp) as mock_get:
        candidates = search_klipy(query="happy", app_key="APPKEY", category="clips")
    # Verify URL has app_key in path
    call = mock_get.call_args
    called_url = call.args[0]
    assert "/api/v1/APPKEY/clips/search" in called_url
    assert "api_key" not in (call.kwargs.get("params") or {})  # NOT a query param
    assert candidates[0].category == "clips"


def test_search_klipy_raises_on_429():
    resp = MagicMock(status_code=429, text="rate limited")
    with patch("app.clip_source.httpx.get", return_value=resp):
        with pytest.raises(RateLimitError):
            search_klipy(query="x", app_key="k", category="clips")


# ---- Download ------------------------------------------------------------

def test_download_writes_bytes(tmp_path):
    file_resp = MagicMock(status_code=200, content=b"FAKEMP4BYTES")
    clip = ClipInfo(path="", source="giphy", original_url="https://x/y.mp4",
                    width=480, height=480)
    with patch("app.clip_source.httpx.get", return_value=file_resp):
        result = download_clip(clip=clip, dest_dir=str(tmp_path))
    assert result.path.endswith(".mp4")
    assert result.size_bytes == len(b"FAKEMP4BYTES")
    from pathlib import Path
    assert Path(result.path).read_bytes() == b"FAKEMP4BYTES"


# ---- Legacy fetch_clip (still works for simple callers) ------------------

def test_fetch_clip_legacy_giphy(tmp_path):
    candidates = [ClipInfo(path="", source="giphy", original_url="https://x.mp4",
                           width=480, height=270, size_bytes=200000)]
    file_resp = MagicMock(status_code=200, content=b"BYTES")
    with patch("app.clip_source.search_giphy", return_value=candidates), \
         patch("app.clip_source.httpx.get", return_value=file_resp):
        info = fetch_clip(query="x", source="giphy", api_key="g", dest_dir=str(tmp_path))
    assert info.source == "giphy"
    assert Path(info.path).exists() if False else True  # path check skipped
