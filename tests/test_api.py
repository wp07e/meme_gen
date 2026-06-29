from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings
from app.models import ClipInfo

client = TestClient(app)


def test_list_templates_route():
    res = client.get("/api/templates")
    assert res.status_code == 200
    assert "caption-top-bottom" in res.json()["templates"]


def test_preview_copy_route(sample_copy):
    with patch("app.main.generate_copy", return_value=sample_copy):
        res = client.post(
            "/api/preview-copy",
            json={"topic": "Monday gym", "tone": "funny",
                  "template": "caption-top-bottom"},
        )
    assert res.status_code == 200
    body = res.json()
    assert "copy" in body
    assert body["copy"]["hook"] == sample_copy.hook


def test_render_route(sample_copy):
    fixture = Path(__file__).parent / "fixtures" / "test_clip.mp4"
    fake_clip = ClipInfo(
        path=str(fixture), source="giphy",
        original_url="x", width=480, height=480,
    )
    settings = Settings()
    # Patch on app.orchestrator: run_pipeline looks these up there, not on app.main.
    with patch("app.main.get_settings", return_value=settings), \
         patch("app.orchestrator.generate_copy", return_value=sample_copy), \
         patch("app.orchestrator.fetch_clip", return_value=fake_clip):
        res = client.post(
            "/api/render",
            json={"topic": "Monday gym", "tone": "funny",
                  "template": "caption-top-bottom", "source": "giphy"},
        )
    assert res.status_code == 200
    assert "output_path" in res.json()
