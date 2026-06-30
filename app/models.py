"""Pydantic data shapes (pipeline) + SQLModel tables (persistence)."""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField, SQLModel


# ---------------------------------------------------------------------------
# Pipeline data shapes (in-memory, passed between stages)
# ---------------------------------------------------------------------------

class FormatPref(str, Enum):
    """User's preferred clip format."""
    clip = "clip"     # video clips only
    gif = "gif"       # animated GIFs only
    auto = "auto"     # try clips first, fall back to GIFs


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
    category: str = "gifs"  # "gifs" | "clips" — which Klipy/Giphy API served it
    original_url: str
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    duration: float | None = None  # seconds, probed via ffprobe (None until probed)

    @property
    def short_edge(self) -> int:
        """Smaller of width/height — used by the quality gate."""
        dims = [d for d in (self.width, self.height) if d]
        return min(dims) if dims else 0

    @property
    def is_clip(self) -> bool:
        """True if this is a video clip (gated for length) vs a GIF (any length)."""
        return self.category == "clips"


class RenderResult(BaseModel):
    """Output of orchestrator / the render route."""
    output_path: str
    copy_result: CopyResult
    clip: ClipInfo


# ---------------------------------------------------------------------------
# SQLModel tables (persistence)
# ---------------------------------------------------------------------------

class Job(SQLModel, table=True):
    """A render job: created on POST /api/render, polled to completion."""
    id: str = SQLField(primary_key=True)
    status: str = SQLField(default="searching", index=True)
        # searching | rendering | done | cancelled | failed
    progress_message: str = SQLField(default="")
    topic: str = SQLField(default="")
    template: str = SQLField(default="")
    format_pref: str = SQLField(default="auto")
    session_id: str = SQLField(default="")
    owner_username: str = SQLField(default="", index=True)  # logged-in creator
    output_filename: str = SQLField(default="")  # basename in output_dir; set on done
    cancel_requested: bool = SQLField(default=False)
    result_json: str | None = SQLField(default=None)  # serialized RenderResult
    error: str | None = SQLField(default=None)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class User(SQLModel, table=True):
    """A login account. Created via the admin screen; admin is seeded on startup."""
    username: str = SQLField(primary_key=True)
    password_hash: str  # pbkdf2_sha256$iters$salt_b64$hash_b64 (see app.security)
    is_admin: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class SeenClip(SQLModel, table=True):
    """Dedupe history: clips already used this session. Survives restarts."""
    id: int | None = SQLField(default=None, primary_key=True)
    session_id: str = SQLField(index=True)
    url: str = SQLField(index=True)
    source: str = SQLField(default="")
    query: str = SQLField(default="")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(SQLModel, table=True):
    """Per-session state: rotation counter + stable Klipy customer_id."""
    session_id: str = SQLField(primary_key=True)
    rotate_index: int = SQLField(default=0)
    customer_id: str = SQLField(default="")


class AssetBundle(SQLModel, table=True):
    """A user-uploaded brand kit for the lower-third-brand template.

    A bundle is a directory on disk (uploads/<owner>/<bundle_id>/) containing
    named PNGs the template references (bottom-bar.png, watermark.png). The
    filenames are fixed by the template contract, so only metadata is stored.
    """
    bundle_id: str = SQLField(primary_key=True)  # uuid hex
    owner_username: str = SQLField(index=True)
    name: str = SQLField(default="")  # user-given label
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
