"""Background render-job worker.

run_render_job() executes: copy → search loop → render, updating the Job row
throughout. Runs in a worker thread (spawned by main.py). Cancel only affects
the search loop; once rendering starts, it runs to completion.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.config import Settings
from app.copywriter import generate_copy, suggest_keywords
from app.clip_source import fetch_best_clip, CancelledError
from app.renderer import render_video
from app.templates import load_template
from app.db import engine
from app.models import Job, SeenClip, SessionState, FormatPref, CopyResult, RenderResult


# ---------------------------------------------------------------------------
# Job CRUD helpers (used by main.py routes + the worker)
# ---------------------------------------------------------------------------

def create_job(*, session_id: str, topic: str, template: str,
               format_pref: FormatPref, owner_username: str = "") -> str:
    """Insert a new Job row, return its id."""
    job_id = uuid.uuid4().hex
    job = Job(
        id=job_id, session_id=session_id, topic=topic, template=template,
        format_pref=format_pref.value, status="searching",
        progress_message="Starting…", owner_username=owner_username,
    )
    with Session(engine) as s:
        s.add(job)
        s.commit()
    return job_id


def get_job(job_id: str) -> Job | None:
    with Session(engine) as s:
        return s.get(Job, job_id)


def request_cancel(job_id: str) -> bool:
    """Set cancel_requested on the job. Returns True if found."""
    with Session(engine) as s:
        job = s.get(Job, job_id)
        if not job:
            return False
        job.cancel_requested = True
        job.updated_at = datetime.now(timezone.utc)
        s.add(job)
        s.commit()
    return True


def _update_job(session: Session, job_id: str, **fields):
    """Internal: mutate a job row in an existing session (worker uses one session)."""
    job = session.get(Job, job_id)
    if not job:
        return
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()


def _resolve_assets_dir(asset_bundle_id: str | None, owner_username: str,
                        settings: Settings) -> Path | None:
    """Resolve a requested bundle to its on-disk directory, or None for defaults.

    asset_bundle_id=="random" picks uniformly among the owner's bundles. Any
    miss (unknown id, unowned, no bundles for random) returns None so the render
    silently falls back to the default assets/ — never hard-fails the render.
    """
    if not asset_bundle_id or not owner_username:
        return None
    from app.bundles import bundle_assets_dir, list_bundles
    if asset_bundle_id == "random":
        owned = list_bundles(owner_username)
        if not owned:
            return None
        import random
        asset_bundle_id = random.choice(owned).bundle_id
    return bundle_assets_dir(asset_bundle_id, owner_username, settings.uploads_dir)


# ---------------------------------------------------------------------------
# SessionState helpers
# ---------------------------------------------------------------------------

def get_or_create_session_state(session_id: str, engine) -> SessionState:
    """Return the SessionState row, creating it (with a stable customer_id) if absent."""
    with Session(engine) as s:
        st = s.get(SessionState, session_id)
        if st:
            return st
        st = SessionState(
            session_id=session_id, rotate_index=0,
            customer_id=f"mg_{uuid.uuid4().hex[:16]}",
        )
        s.add(st)
        s.commit()
        s.refresh(st)
        return st


def next_rotate_start(session_id: str, engine) -> str:
    """Atomically increment and return the next starting provider ('giphy'|'klipy')."""
    with Session(engine) as s:
        st = get_or_create_session_state(session_id, engine)
        # Re-fetch within this session for update.
        st = s.get(SessionState, session_id)
        st.rotate_index += 1
        s.add(st)
        s.commit()
        return "klipy" if st.rotate_index % 2 == 0 else "giphy"


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

def run_render_job(
    *, job_id: str, topic: str, tone: str, template_name: str,
    format_pref: FormatPref, clip_keyword: str | None, session_id: str,
    settings: Settings, copy_result: CopyResult | None = None,
    asset_bundle_id: str | None = None, owner_username: str = "",
    include_audio: bool = False,
) -> None:
    """Run the full pipeline in a worker thread, updating the Job row.

    Designed to be invoked via threading.Thread(target=run_render_job, kwargs=...).
    Never raises — all errors land in job.status='failed' / job.error.
    """
    session = Session(engine)
    try:
        spec = load_template(template_name)

        # Resolve an asset bundle (per-render PNG swap) if one was requested.
        # "random" picks among the owner's bundles server-side. Falls back to the
        # default assets/ dir if the bundle is missing/unowned — never hard-fails.
        assets_dir = _resolve_assets_dir(asset_bundle_id, owner_username, settings)

        # 1. Copy (if not supplied by the UI's preview step).
        if copy_result is None:
            _update_job(session, job_id, progress_message="Writing copy…")
            copy_result = generate_copy(
                topic=topic, tone=tone,
                overlay_slot_count=len(spec.positions),
                api_key=settings.moonshot_api_key,
                model=settings.moonshot_model,
                base_url=settings.moonshot_base_url,
            )

        # 2. Clip search loop.
        st = get_or_create_session_state(session_id, engine)
        rotate_start = "giphy" if st.rotate_index % 2 == 0 else "klipy"
        query = (clip_keyword or "").strip() or topic

        def on_attempt(msg: str):
            _update_job(session, job_id, status="searching", progress_message=msg)

        def is_cancelled() -> bool:
            job = session.get(Job, job_id)
            return bool(job and job.cancel_requested)

        def suggest_fn(q: str) -> list[str]:
            return suggest_keywords(
                query=q, api_key=settings.moonshot_api_key,
                model=settings.moonshot_model, base_url=settings.moonshot_base_url,
            )

        try:
            clip = fetch_best_clip(
                query=query, format_pref=format_pref, rotate_start=rotate_start,
                giphy_key=settings.giphy_api_key, klipy_key=settings.klipy_api_key,
                klipy_customer_id=st.customer_id, session_id=session_id,
                session=session, dest_dir=settings.tmp_dir,
                on_attempt=on_attempt, is_cancelled=is_cancelled,
                suggest_keywords_fn=suggest_fn,
            )
        except CancelledError:
            _update_job(session, job_id, status="cancelled",
                        progress_message="Cancelled during clip search.")
            return

        # Record the chosen clip so future renders dedupe it.
        session.add(SeenClip(session_id=session_id, url=clip.original_url,
                             source=clip.source, query=query))
        session.commit()

        # 3. Render (NOT cancellable — runs to completion per the design decision).
        _update_job(session, job_id, status="rendering",
                    progress_message="Clip found. Rendering — please wait (~20-40s)…")
        out_path = render_video(
            clip=clip, copy=copy_result, template=spec, output_dir=settings.output_dir,
            assets_dir=assets_dir, include_audio=include_audio,
        )

        result = RenderResult(output_path=out_path, copy_result=copy_result, clip=clip)
        _update_job(session, job_id, status="done", progress_message="Done.",
                    result_json=result.model_dump_json(),
                    output_filename=out_path.rsplit("/", 1)[-1])

    except Exception as e:
        _update_job(session, job_id, status="failed",
                    progress_message=f"Failed: {e}", error=str(e))
    finally:
        session.close()
