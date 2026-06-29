from unittest.mock import patch, MagicMock

import pytest

from app.clip_source import fetch_clip


def test_fetch_clip_giphy_downloads_mp4(tmp_path):
    fake_body = {
        "data": [
            {
                "images": {
                    "original": {
                        "mp4": "https://media.giphy.com/media/x/giphy.mp4",
                        "mp4_size": "12345",
                        "width": "480",
                        "height": "480",
                    }
                }
            }
        ]
    }
    # Mock httpx.get for the search call AND the file download.
    search_response = MagicMock(status_code=200)
    search_response.json.return_value = fake_body
    search_response.raise_for_status = MagicMock()
    file_response = MagicMock(status_code=200, content=b"FAKEMP4BYTES")

    with patch("app.clip_source.httpx.get", side_effect=[search_response, file_response]):
        info = fetch_clip(
            query="monday gym",
            source="giphy",
            api_key="g_key",
            dest_dir=str(tmp_path),
        )
    assert info.source == "giphy"
    assert info.path.endswith(".mp4")
    assert info.width == 480
    from pathlib import Path
    assert Path(info.path).read_bytes() == b"FAKEMP4BYTES"


def test_fetch_clip_no_results_raises(tmp_path):
    search_response = MagicMock(status_code=200)
    search_response.json.return_value = {"data": []}
    search_response.raise_for_status = MagicMock()
    with patch("app.clip_source.httpx.get", return_value=search_response):
        with pytest.raises(LookupError):
            fetch_clip(
                query="nothing", source="giphy",
                api_key="g_key", dest_dir=str(tmp_path),
            )
