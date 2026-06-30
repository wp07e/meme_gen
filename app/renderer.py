"""Composite clip + overlays + text into a final MP4 via MoviePy 2.x."""
import datetime as dt
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from moviepy import (
    VideoFileClip,
    VideoClip,
    TextClip,
    ImageClip,
    CompositeVideoClip,
)

from app.models import ClipInfo, CopyResult
from app.templates import TemplateSpec

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Background blur radius (px) and dim factor for the blurred-fill layer.
BLUR_RADIUS = 20
BG_DIM = 0.5


def render_video(
    *, clip: ClipInfo, copy: CopyResult, template: TemplateSpec, output_dir: str,
    assets_dir: Path | None = None,
) -> str:
    base = VideoFileClip(clip.path)
    W, H = template.width, template.height

    # Composite the clip with a blurred background fill (nothing cropped):
    # a blurred, dimmed copy fills the frame, the sharp clip sits contained on top.
    sized_layers = _build_blur_fill(base, W, H)
    duration = base.duration
    layers = [layer.with_duration(duration) for layer in sized_layers]

    # Static image overlays (Canva PNGs). Resolve from the bundle dir when one
    # is supplied (per-render swap), else the default assets/ directory.
    adir = Path(assets_dir) if assets_dir else ASSETS_DIR
    for ov in template.overlays:
        img_path = adir / ov.file
        if img_path.exists():
            img = ImageClip(str(img_path)).with_duration(duration)
            img = img.with_position((ov.x, ov.y))
            layers.append(img)

    # Distribute overlay lines across template slots. If there are more lines
    # than slots, fold the extras into the last slot (joined by ' / ') so no
    # content is silently dropped. If fewer, only filled slots get text.
    slots = list(template.positions.keys())
    lines = list(copy.overlay_lines)
    if len(lines) > len(slots) and slots:
        # Merge tail into the last slot.
        lines = lines[: len(slots) - 1] + [" / ".join(lines[len(slots) - 1:])]

    # Text layers mapped to positions by order: top, bottom, ...
    for slot_name, line in zip(slots, lines):
        pos = template.positions[slot_name]
        txt = TextClip(
            text=line,
            font=template.font,
            font_size=template.font_size,
            color=template.font_color,
            stroke_color=template.stroke_color,
            stroke_width=template.stroke_width,
            size=(template.width - 80, None),
            method="caption",
            text_align="center",
        ).with_duration(duration)
        txt = txt.with_position(_resolve_position(pos, template, txt.size))
        layers.append(txt)

    composite = CompositeVideoClip(layers, size=(template.width, template.height))
    if composite.audio:
        composite = composite.with_audio(composite.audio.with_volume_scaled(0.0))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{stamp}_render.mp4"
    composite.write_videofile(
        str(out_path),
        codec="libx264",
        audio_codec="aac",
        fps=30,
        preset="medium",
        logger=None,
    )
    base.close()
    return str(out_path)


def _build_blur_fill(clip: VideoFileClip, W: int, H: int) -> list:
    """Return [blurred_background, sharp_foreground] clips that together fill W×H.

    Background: the clip scaled to COVER the frame, center-cropped to exact size,
    then blurred and dimmed — fills empty space without cropping the subject.
    Foreground: the clip scaled to CONTAIN (whole image visible), centered.
    Used as the bottom two layers of the composite.
    """
    sw, sh = clip.w, clip.h

    # --- Background: cover + crop + blur ---
    cover_r = max(W / sw, H / sh)
    cw, ch = int(sw * cover_r), int(sh * cover_r)
    bg_scaled = clip.resized((cw, ch))
    bx = (cw - W) / 2
    by = (ch - H) / 2
    bg_cropped = bg_scaled.cropped(x1=bx, y1=by, x2=bx + W, y2=by + H)

    def _blurred_dim_frame(get_frame, t):
        frame = get_frame(t)
        img = Image.fromarray(frame).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        return (np.array(img) * BG_DIM).astype("uint8")

    bg = VideoClip(
        lambda t: _blurred_dim_frame(bg_cropped.get_frame, t),
        duration=clip.duration,
    ).with_fps(clip.fps or 30)

    # --- Foreground: contain (fit whole image) + center ---
    fit_r = min(W / sw, H / sh)
    fw, fh = int(sw * fit_r), int(sh * fit_r)
    fg = clip.resized((fw, fh)).with_position(((W - fw) / 2, (H - fh) / 2))

    return [bg, fg]


def _resolve_position(pos, template: TemplateSpec, text_size: tuple[int, int]):
    """Translate a template position spec into a MoviePy position tuple."""
    tw, th = text_size
    x = pos.x
    y = pos.y
    px = template.width / 2 - tw / 2 if x == "center" else int(x)
    if y == "center":
        py = template.height / 2 - th / 2
    elif y.startswith("bottom-"):
        py = template.height - th - int(y.split("-")[1])
    elif y.startswith("top-"):
        py = int(y.split("-")[1])
    else:
        py = int(y)
    return (px, py)
