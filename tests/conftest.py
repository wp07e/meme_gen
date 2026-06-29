"""Shared fixtures."""
import pytest

from app.models import CopyResult, ClipInfo


@pytest.fixture
def sample_copy():
    return CopyResult(
        caption="When Monday hits and you forgot it was a holiday 💀 #monday",
        hook="POV: the alarm was lying",
        overlay_lines=["ME ON MONDAY", "ALSO ME:"],
    )


@pytest.fixture
def sample_clip_info(tmp_path):
    return ClipInfo(
        path=str(tmp_path / "clip.mp4"),
        source="giphy",
        original_url="https://media.giphy.com/media/abc/giphy.mp4",
        width=480,
        height=480,
    )
