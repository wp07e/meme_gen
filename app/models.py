"""Pydantic data shapes passed between pipeline stages."""
from pydantic import BaseModel, Field


class CopyResult(BaseModel):
    """Output of copywriter.py."""
    caption: str = Field(description="Post caption (for FB/IG text field)")
    hook: str = Field(description="Short hook shown on screen briefly")
    overlay_lines: list[str] = Field(
        description="Lines of text rendered onto the video (e.g. top/bottom)"
    )


class ClipInfo(BaseModel):
    """Output of clip_source.py."""
    path: str
    source: str  # "giphy" | "klipy"
    original_url: str
    width: int | None = None
    height: int | None = None


class RenderRequest(BaseModel):
    """Input to the orchestrator from the web UI."""
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"
    source: str = "giphy"  # "giphy" | "klipy"
    # When the UI previews copy first, it posts the edited copy back:
    copy_result: CopyResult | None = None


class RenderResult(BaseModel):
    """Output of orchestrator / the render route."""
    output_path: str
    copy_result: CopyResult
    clip: ClipInfo
