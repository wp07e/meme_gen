"""Composite clip + overlays + text into a final MP4 via MoviePy 2.x."""
import datetime as dt
from pathlib import Path

from moviepy import (
    VideoFileClip,
    TextClip,
    ImageClip,
    CompositeVideoClip,
)

from app.models import ClipInfo, CopyResult
from app.templates import TemplateSpec

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def render_video(
    *, clip: ClipInfo, copy: CopyResult, template: TemplateSpec, output_dir: str
) -> str:
    base = VideoFileClip(clip.path)

    # Resize/crop to the template aspect ratio.
    sized = _fit_to_size(base, template.width, template.height)
    duration = sized.duration

    layers = [sized]

    # Static image overlays (Canva PNGs).
    for ov in template.overlays:
        img_path = ASSETS_DIR / ov.file
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


def _fit_to_size(clip: VideoFileClip, width: int, height: int) -> VideoFileClip:
    """Resize preserving aspect, then crop center to exact target size."""
    target_ratio = width / height
    src_ratio = clip.w / clip.h
    if src_ratio > target_ratio:
        # Source is wider — fit height, crop width.
        scaled = clip.resized(height=height)
    else:
        scaled = clip.resized(width=width)
    x_center = (scaled.w - width) / 2
    y_center = (scaled.h - height) / 2
    return scaled.cropped(x1=x_center, y1=y_center, x2=x_center + width, y2=y_center + height)


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
