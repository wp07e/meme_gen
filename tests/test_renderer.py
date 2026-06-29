from pathlib import Path

from app.renderer import render_video
from app.models import CopyResult, ClipInfo
from app.templates import load_template

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_render_video_produces_mp4(tmp_path, sample_copy):
    clip = ClipInfo(
        path=str(FIXTURE),
        source="giphy",
        original_url="x",
        width=480,
        height=480,
    )
    spec = load_template("caption-top-bottom")
    out = render_video(
        clip=clip,
        copy=sample_copy,
        template=spec,
        output_dir=str(tmp_path),
    )
    assert Path(out).exists()
    assert out.endswith(".mp4")
    assert Path(out).stat().st_size > 0
    # Should be square 1080x1080 per the template.
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    w, h = probe.stdout.strip().split(",")
    assert (w, h) == ("1080", "1080")
