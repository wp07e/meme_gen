"""FastAPI web app — thin wrapper over the pipeline (async job + polling)."""
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_settings
from app.copywriter import generate_copy
from app.db import init_db
from app.jobs import create_job, get_job, request_cancel, run_render_job
from app.models import CopyResult, FormatPref
from app.templates import list_templates, load_template

app = FastAPI(title="meme_gen")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSION_COOKIE = "meme_gen_session"


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _ensure_session(request: Request) -> str:
    """Return the browser session id (set a cookie if absent)."""
    sid = request.cookies.get(SESSION_COOKIE)
    return sid if sid else f"sess_{request.client.host}_{id(request)}"


class PreviewCopyRequest(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"


class RenderReq(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"
    format_pref: str = "auto"  # "clip" | "gif" | "auto"
    copy_data: dict | None = None
    clip_keyword: str | None = None


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


@app.post("/api/render")
def api_render(req: RenderReq, request: Request):
    """Create a render job and spawn the worker; returns {job_id} immediately."""
    settings = get_settings()
    session_id = _ensure_session(request)
    try:
        fmt = FormatPref(req.format_pref)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"format_pref must be clip|gif|auto")
    try:
        template_spec = load_template(req.template)
    except FileNotFoundError:
        raise HTTPException(status_code=422, detail=f"Unknown template '{req.template}'")

    copy_obj = CopyResult(**req.copy_data) if req.copy_data else None
    job_id = create_job(session_id=session_id, topic=req.topic,
                        template=req.template, format_pref=fmt)

    # Spawn the worker in a background thread; do NOT block.
    threading.Thread(
        target=run_render_job,
        kwargs=dict(
            job_id=job_id, topic=req.topic, tone=req.tone,
            template_name=req.template, format_pref=fmt,
            clip_keyword=req.clip_keyword, session_id=session_id,
            settings=settings, copy_result=copy_obj,
        ),
        daemon=True,
    ).start()

    response = Response(content='{"job_id": "%s"}' % job_id,
                        media_type="application/json")
    if not request.cookies.get(SESSION_COOKIE):
        response.set_cookie(SESSION_COOKIE, session_id, max_age=60 * 60 * 24 * 30)
    return response


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    """Poll a job's status. Polled by the frontend every ~1.5s."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    result = None
    if job.result_json:
        import json
        result = json.loads(job.result_json)
    return {
        "status": job.status,
        "progress_message": job.progress_message,
        "result": result,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
    }


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str):
    """Request cancellation of the search loop (render phase is not interruptible)."""
    if not request_cancel(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True}


@app.get("/api/files/{name}")
def api_download(name: str):
    settings = get_settings()
    p = Path(settings.output_dir) / name
    if not p.exists() or ".." in name:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(p, media_type="video/mp4", filename=name)
