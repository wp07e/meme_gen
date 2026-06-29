"""FastAPI web app — thin wrapper over the pipeline."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_settings
from app.copywriter import generate_copy
from app.clip_source import fetch_clip
from app.orchestrator import run_pipeline
from app.templates import list_templates, load_template

app = FastAPI(title="meme_gen")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PreviewCopyRequest(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/templates")
def api_templates():
    return {"templates": list_templates()}


@app.post("/api/preview-copy")
def api_preview_copy(req: PreviewCopyRequest):
    settings = get_settings()
    spec = load_template(req.template)
    try:
        copy = generate_copy(
            topic=req.topic, tone=req.tone,
            overlay_slot_count=len(spec.positions),
            api_key=settings.moonshot_api_key,
            model=settings.moonshot_model,
            base_url=settings.moonshot_base_url,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Copy generation failed: {e}")
    return {"copy": copy.model_dump()}


class RenderReq(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"
    source: str = "giphy"
    copy_data: dict | None = None


@app.post("/api/render")
def api_render(req: RenderReq):
    settings = get_settings()
    from app.models import CopyResult
    copy_obj = CopyResult(**req.copy_data) if req.copy_data else None
    try:
        result = run_pipeline(
            topic=req.topic, tone=req.tone,
            template_name=req.template, source=req.source,
            settings=settings, copy_result=copy_obj,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")
    return result.model_dump()


@app.get("/api/files/{name}")
def api_download(name: str):
    settings = get_settings()
    p = Path(settings.output_dir) / name
    if not p.exists() or ".." in name:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(p, media_type="video/mp4", filename=name)
