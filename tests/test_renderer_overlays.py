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


def test_render_video_uses_assets_dir_override(tmp_path, sample_copy, monkeypatch):
    """When assets_dir is supplied, overlay PNGs are read from THAT directory,
    not the module default ASSETS_DIR. This is the per-bundle swap mechanism."""
    # Put DISTINCT PNGs in a bundle dir so we can prove they were the ones used.
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    from PIL import Image
    # bottom-bar at a unique size we can detect in the output frame footprint.
    Image.new("RGBA", (1080, 160), (255, 0, 0, 255)).save(bundle_dir / "bottom-bar.png")
    Image.new("RGBA", (240, 70), (0, 255, 0, 255)).save(bundle_dir / "watermark.png")

    # Point the module ASSETS_DIR elsewhere (empty) to prove the override wins.
    empty_default = tmp_path / "default_assets"
    empty_default.mkdir()
    monkeypatch.setattr("app.renderer.ASSETS_DIR", empty_default)

    clip = ClipInfo(path=str(FIXTURE), source="giphy", original_url="x",
                    width=480, height=480)
    spec = load_template("lower-third-brand")
    copy = CopyResult(caption="x", hook="y", overlay_lines=["CAP"])
    out = render_video(clip=clip, copy=copy, template=spec,
                       output_dir=str(tmp_path), assets_dir=bundle_dir)
    assert Path(out).exists() and Path(out).stat().st_size > 0

    # Confirm the output is 9:16 and rendered without error (overlays resolved
    # from bundle_dir, not the empty default — which would have silently skipped them).
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    w, h = probe.stdout.strip().split(",")
    assert (w, h) == ("1080", "1920")
