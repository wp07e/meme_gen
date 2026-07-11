from pathlib import Path
from unittest.mock import patch

from app.orchestrator import run_pipeline
from app.config import Settings
from app.models import ClipInfo

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_run_pipeline_chains_stages(tmp_path, sample_copy):
    settings = Settings(
        giphy_api_key="g", klipy_api_key="k",
        openrouter_api_key="m", openrouter_model="openai/gpt-4o-mini",
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


def test_run_pipeline_clip_keyword_overrides_topic_query(tmp_path, sample_copy):
    """When clip_keyword is given, it is used as the search query, not topic."""
    settings = Settings(
        giphy_api_key="g", klipy_api_key="k",
        openrouter_api_key="m", openrouter_model="openai/gpt-4o-mini",
        output_dir=str(tmp_path / "out"), tmp_dir=str(tmp_path / "tmp"),
    )
    fake_clip = ClipInfo(
        path=str(FIXTURE), source="giphy",
        original_url="x", width=480, height=480,
    )
    with patch("app.orchestrator.generate_copy", return_value=sample_copy), \
         patch("app.orchestrator.fetch_clip", return_value=fake_clip) as fc:
        run_pipeline(
            topic="Monday motivation, gym grind", tone="funny",
            template_name="caption-top-bottom",
            source="giphy", settings=settings,
            clip_keyword="workout fail",
        )
    # fetch_clip must be called with the keyword, not the verbose topic.
    fc.assert_called_once()
    assert fc.call_args.kwargs["query"] == "workout fail"


def test_run_pipeline_falls_back_to_topic_when_no_keyword(tmp_path, sample_copy):
    """Without clip_keyword, the topic is used as the search query."""
    settings = Settings(
        giphy_api_key="g", klipy_api_key="k",
        openrouter_api_key="m", openrouter_model="openai/gpt-4o-mini",
        output_dir=str(tmp_path / "out"), tmp_dir=str(tmp_path / "tmp"),
    )
    fake_clip = ClipInfo(
        path=str(FIXTURE), source="giphy",
        original_url="x", width=480, height=480,
    )
    with patch("app.orchestrator.generate_copy", return_value=sample_copy), \
         patch("app.orchestrator.fetch_clip", return_value=fake_clip) as fc:
        run_pipeline(
            topic="monday gym", tone="funny",
            template_name="caption-top-bottom",
            source="giphy", settings=settings,
        )
    fc.assert_called_once()
    assert fc.call_args.kwargs["query"] == "monday gym"
