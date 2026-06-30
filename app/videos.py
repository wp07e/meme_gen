"""Per-user video library: list, delete (row + file), bulk-delete."""
import json
import os
from pathlib import Path

from sqlmodel import Session, select

from app.db import engine
from app.models import Job


def _output_path(filename: str, output_dir: str) -> Path:
    return Path(output_dir) / filename


def list_done_videos(owner_username: str) -> list[Job]:
    """Done jobs owned by the user, newest first."""
    with Session(engine) as s:
        stmt = (
            select(Job)
            .where(Job.owner_username == owner_username)
            .where(Job.status == "done")
            .order_by(Job.created_at.desc())  # type: ignore[union-attr]
        )
        return list(s.exec(stmt).all())


def video_view(job: Job) -> dict:
    """Shape a Job into the JSON the library cards render."""
    filename = job.output_filename
    if not filename and job.result_json:
        # Defensive: fall back to result_json if output_filename wasn't set.
        try:
            filename = json.loads(job.result_json).get("output_path", "").rsplit("/", 1)[-1]
        except Exception:
            filename = ""
    return {
        "id": job.id,
        "topic": job.topic or "(untitled)",
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "filename": filename,
        "url": f"/api/files/{filename}" if filename else "",
    }


def delete_video(job_id: str, owner_username: str, output_dir: str) -> bool:
    """Delete one video if owned by the caller. Removes the DB row and the file
    on disk (file missing is not an error). Returns True if something was deleted."""
    with Session(engine) as s:
        job = s.get(Job, job_id)
        if job is None or job.owner_username != owner_username:
            return False
        filename = job.output_filename
        s.delete(job)
        s.commit()
    if filename:
        try:
            _output_path(filename, output_dir).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Row is gone; don't fail the request over a file-system hiccup.
            pass
    return True


def bulk_delete_videos(job_ids: list[str], owner_username: str, output_dir: str) -> tuple[int, list[str]]:
    """Delete each owned job; return (deleted_count, skipped_ids)."""
    deleted = 0
    skipped: list[str] = []
    for jid in job_ids:
        if delete_video(jid, owner_username, output_dir):
            deleted += 1
        else:
            skipped.append(jid)
    return deleted, skipped
