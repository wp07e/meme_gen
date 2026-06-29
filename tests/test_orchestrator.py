from pathlib import Path
from unittest.mock import patch

from app.orchestrator import run_pipeline
from app.config import Settings
from app.models import ClipInfo

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_run_pipeline_chains_stages(tmp_path, sample_copy):
    settings = Settings(
        giphy_api_key="g", klipy_api_key="k",
        moonshot_api_key="m", moonshot_model="kimi-k2",
        output_dir=str(tmp_path / "out"), tmp_dir=str(tmp_path / "tmp"),
    )
    fake_clip = ClipInfo(
        path=str(FIXTURE), source="giphy",
        original_url="x", width=480, height=480,
    )
    with patch("app.orchestrator.generate_copy", return_value=sample_copy) as gc, \
         patch("app.orchestrator.fetch_clip", return_value=fake_clip) as fc:
        result = run_pipeline(
            topic="Monday gym", tone="funny",
            template_name="caption-top-bottom",
            source="giphy", settings=settings,
        )
    assert Path(result.output_path).exists()
    gc.assert_called_once()
    fc.assert_called_once()
