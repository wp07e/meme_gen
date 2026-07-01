"""FastAPI web app — login + async render pipeline + per-user video library."""
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.auth import (
    Principal,
    authenticate,
    list_users,
    create_user as create_user_helper,
    delete_user as delete_user_helper,
    require_admin,
    require_user,
    seed_admin,
    set_session_cookie_value,
)
from app.config import DEFAULT_SECRET_KEY, get_settings
from app.copywriter import generate_copy
from app.db import init_db, run_migrations
from app.jobs import create_job, get_job, request_cancel, run_render_job
from app.models import CopyResult, FormatPref
from app.security import SESSION_COOKIE
from app.templates import list_templates, load_template
from app.videos import bulk_delete_videos, delete_video, list_done_videos, video_view
from app.bundles import BundleError, create_bundle, delete_bundle, list_bundles

app = FastAPI(title="meme_gen")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Placeholder tokens in static/index.html are replaced with the real GTM container ID
# at serve time so the ID never has to live in the public repo.
GTM_HEAD_PLACEHOLDER = "<!-- __GTM_HEAD__ -->"
GTM_BODY_PLACEHOLDER = "<!-- __GTM_BODY__ -->"

GTM_HEAD_TEMPLATE = """<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){{w[l]=w[l]||[];w[l].push({{'gtm.start':
new Date().getTime(),event:'gtm.js'}});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
}})(window,document,'script','dataLayer','{gtm_id}');</script>
<!-- End Google Tag Manager -->"""

GTM_BODY_TEMPLATE = """<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={gtm_id}"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""

SESSION_COOKIE_ANON = "meme_gen_session"  # anonymous clip-dedupe session (unchanged)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    run_migrations()
    settings = get_settings()
    if settings.secret_key == DEFAULT_SECRET_KEY:
        print("WARNING: SECRET_KEY is the insecure default. Set SECRET_KEY in .env before deploying.")
    seed_admin(settings)


def _ensure_anon_session(request: Request) -> str:
    """Anonymous browser session id (clip rotation/dedupe). Unrelated to login."""
    sid = request.cookies.get(SESSION_COOKIE_ANON)
    return sid if sid else f"sess_{request.client.host}_{id(request)}"


# --------------------------------------------------------------------------- #
# Pydantic request models
# --------------------------------------------------------------------------- #

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
    asset_bundle_id: str | None = None  # bundle id, or "random"
    include_audio: bool = False  # keep clip audio in the output (muted by default)


class LoginReq(BaseModel):
    username: str
    password: str


class CreateUserReq(BaseModel):
    username: str
    password: str


class BulkDeleteReq(BaseModel):
    job_ids: list[str]


# --------------------------------------------------------------------------- #
# Auth + page routes (open)
# --------------------------------------------------------------------------- #

@app.get("/")
def index():
    settings = get_settings()
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if settings.gtm_container_id:
        head = GTM_HEAD_TEMPLATE.format(gtm_id=settings.gtm_container_id)
        body = GTM_BODY_TEMPLATE.format(gtm_id=settings.gtm_container_id)
    else:
        head = "<!-- GTM disabled: set GTM_CONTAINER_ID in .env to enable -->"
        body = ""
    html = html.replace(GTM_HEAD_PLACEHOLDER, head)
    html = html.replace(GTM_BODY_PLACEHOLDER, body)
    return HTMLResponse(content=html)


@app.post("/api/login")
def api_login(req: LoginReq, request: Request, response: Response):
    """Verify credentials; set the signed session cookie on success."""
    user = authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    name, value, max_age = set_session_cookie_value(user.username, get_settings().secret_key)
    response.set_cookie(name, value, max_age=max_age, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https")
    return {"username": user.username, "is_admin": user.is_admin}


@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/me")
def api_me(user: Principal = Depends(require_user)):
    return {"username": user.username, "is_admin": user.is_admin}


# --------------------------------------------------------------------------- #
# Generator pipeline (auth required)
# --------------------------------------------------------------------------- #

@app.get("/api/templates")
def api_templates(_user: Principal = Depends(require_user)):
    return {"templates": list_templates()}


@app.post("/api/preview-copy")
def api_preview_copy(req: PreviewCopyRequest, _user: Principal = Depends(require_user)):
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
def api_render(req: RenderReq, request: Request, user: Principal = Depends(require_user)):
    """Create a render job and spawn the worker; returns {job_id} immediately."""
    settings = get_settings()
    anon_session = _ensure_anon_session(request)  # for clip rotation/dedupe
    try:
        fmt = FormatPref(req.format_pref)
    except ValueError:
        raise HTTPException(status_code=422, detail="format_pref must be clip|gif|auto")
    try:
        load_template(req.template)
    except FileNotFoundError:
        raise HTTPException(status_code=422, detail=f"Unknown template '{req.template}'")

    copy_obj = CopyResult(**req.copy_data) if req.copy_data else None
    job_id = create_job(session_id=anon_session, topic=req.topic,
                        template=req.template, format_pref=fmt,
                        owner_username=user.username)

    # Spawn the worker in a background thread; do NOT block.
    threading.Thread(
        target=run_render_job,
        kwargs=dict(
            job_id=job_id, topic=req.topic, tone=req.tone,
            template_name=req.template, format_pref=fmt,
            clip_keyword=req.clip_keyword, session_id=anon_session,
            settings=settings, copy_result=copy_obj,
            asset_bundle_id=req.asset_bundle_id, owner_username=user.username,
            include_audio=req.include_audio,
        ),
        daemon=True,
    ).start()

    body = Response(content='{"job_id": "%s"}' % job_id, media_type="application/json")
    if not request.cookies.get(SESSION_COOKIE_ANON):
        body.set_cookie(SESSION_COOKIE_ANON, anon_session, max_age=60 * 60 * 24 * 30)
    return body


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, _user: Principal = Depends(require_user)):
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
def api_cancel_job(job_id: str, _user: Principal = Depends(require_user)):
    """Request cancellation of the search loop (render phase is not interruptible)."""
    if not request_cancel(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True}


@app.get("/api/files/{name}")
def api_download(name: str, user: Principal = Depends(require_user)):
    """Serve a finished video — but only if it belongs to the caller.

    Resolves the filename -> Job row -> owner; 404 (no existence leak) if the
    file isn't owned by the logged-in user. Closes filename-guessing on a
    public deploy.
    """
    from sqlmodel import Session, select
    from app.db import engine
    from app.models import Job
    if ".." in name or "/" in name:
        raise HTTPException(status_code=404, detail="file not found")
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.output_filename == name)).first()
    if job is None or job.owner_username != user.username:
        raise HTTPException(status_code=404, detail="file not found")
    p = Path(get_settings().output_dir) / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(p, media_type="video/mp4", filename=name)


# --------------------------------------------------------------------------- #
# Per-user video library (auth required)
# --------------------------------------------------------------------------- #

@app.get("/api/videos")
def api_videos(user: Principal = Depends(require_user)):
    jobs = list_done_videos(user.username)
    return {"videos": [video_view(j) for j in jobs]}


@app.delete("/api/videos/{job_id}")
def api_delete_video(job_id: str, user: Principal = Depends(require_user)):
    settings = get_settings()
    ok = delete_video(job_id, user.username, settings.output_dir)
    if not ok:
        raise HTTPException(status_code=404, detail="video not found")
    return {"ok": True}


@app.post("/api/videos/bulk-delete")
def api_bulk_delete_videos(req: BulkDeleteReq, user: Principal = Depends(require_user)):
    settings = get_settings()
    deleted, skipped = bulk_delete_videos(req.job_ids, user.username, settings.output_dir)
    return {"deleted": deleted, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Asset bundles (auth required, per-user) — lower-third-brand brand kits
# --------------------------------------------------------------------------- #

@app.get("/api/bundles")
def api_list_bundles(user: Principal = Depends(require_user)):
    bundles = list_bundles(user.username)
    return {"bundles": [
        {"bundle_id": b.bundle_id, "name": b.name,
         "created_at": b.created_at.isoformat() if b.created_at else None}
        for b in bundles
    ]}


@app.post("/api/bundles")
def api_create_bundle(
    name: str = Form(""),
    bottom_bar: UploadFile = File(...),
    watermark: UploadFile = File(...),
    user: Principal = Depends(require_user),
):
    settings = get_settings()
    try:
        bundle = create_bundle(
            owner_username=user.username, name=name,
            bottom_bar=bottom_bar, watermark=watermark,
            uploads_dir=settings.uploads_dir,
        )
    except BundleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"bundle_id": bundle.bundle_id, "name": bundle.name}


@app.delete("/api/bundles/{bundle_id}")
def api_delete_bundle(bundle_id: str, user: Principal = Depends(require_user)):
    settings = get_settings()
    if not delete_bundle(bundle_id, user.username, settings.uploads_dir):
        raise HTTPException(status_code=404, detail="bundle not found")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Admin (admin only) — manage login accounts
# --------------------------------------------------------------------------- #

@app.get("/api/admin/users")
def api_list_users(_user: Principal = Depends(require_admin)):
    users = list_users()
    return {"users": [
        {"username": u.username, "is_admin": u.is_admin,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in users
    ]}


@app.post("/api/admin/users")
def api_create_user(req: CreateUserReq, _user: Principal = Depends(require_admin)):
    try:
        create_user_helper(req.username, req.password)
    except ValueError as e:
        msg = str(e)
        status = 409 if "exists" in msg else 400
        raise HTTPException(status_code=status, detail=msg)
    return {"ok": True}


@app.delete("/api/admin/users/{username}")
def api_delete_user(username: str, _user: Principal = Depends(require_admin)):
    settings = get_settings()
    try:
        delete_user_helper(username, settings)
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg else 400
        raise HTTPException(status_code=status, detail=msg)
    return {"ok": True}
