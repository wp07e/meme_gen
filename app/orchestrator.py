"""Chain copywriter → clip_source → renderer into one render."""
from app.config import Settings
from app.copywriter import generate_copy
from app.clip_source import fetch_clip
from app.renderer import render_video
from app.templates import load_template
from app.models import CopyResult, RenderResult


def run_pipeline(
    *,
    topic: str,
    tone: str,
    template_name: str,
    source: str,
    settings: Settings,
    copy_result: CopyResult | None = None,
    clip_keyword: str | None = None,
) -> RenderResult:
    spec = load_template(template_name)
    slot_count = len(spec.positions)

    if copy_result is None:
        copy_result = generate_copy(
            topic=topic,
            tone=tone,
            overlay_slot_count=slot_count,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
        )

    # Clip search uses an explicit keyword if provided; otherwise falls back to
    # the raw topic. The keyword usually yields better Giphy/Klipy results than
    # a long topic phrase, since clip search is keyword-matched, not semantic.
    query = (clip_keyword or "").strip() or topic
    clip = fetch_clip(
        query=query,
        source=source,
        api_key=settings.giphy_api_key if source == "giphy" else settings.klipy_api_key,
        dest_dir=settings.tmp_dir,
    )

    out_path = render_video(
        clip=clip, copy=copy_result, template=spec, output_dir=settings.output_dir,
    )
    return RenderResult(output_path=out_path, copy_result=copy_result, clip=clip)
