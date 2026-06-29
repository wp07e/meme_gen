from pathlib import Path
from unittest.mock import patch

from app.renderer import render_video
from app.models import ClipInfo, CopyResult
from app.templates import load_template

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_render_with_overlays(tmp_path, sample_copy, monkeypatch):
    # Point ASSETS_DIR at a tmp dir with a real (tiny) PNG so the test is
    # hermetic and doesn't depend on the actual Canva/Pillow assets existing.
    fake_assets = tmp_path / "assets"
    fake_assets.mkdir()
    from PIL import Image
    Image.new("RGBA", (1080, 160), (0, 0, 0, 120)).save(fake_assets / "bottom-bar.png")
    Image.new("RGBA", (240, 80), (0, 0, 0, 120)).save(fake_assets / "watermark.png")
    monkeypatch.setattr("app.renderer.ASSETS_DIR", fake_assets)

    clip = ClipInfo(path=str(FIXTURE), source="giphy", original_url="x",
                    width=480, height=480)
    spec = load_template("lower-third-brand")  # 9:16, has overlays
    # supply one overlay line to match the single 'caption' position
    copy = CopyResult(caption="x", hook="y", overlay_lines=["BRANDED CAPTION"])
    out = render_video(clip=clip, copy=copy, template=spec, output_dir=str(tmp_path))
    assert Path(out).exists() and Path(out).stat().st_size > 0

    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    w, h = probe.stdout.strip().split(",")
    assert (w, h) == ("1080", "1920"), "lower-third-brand should render 9:16"
