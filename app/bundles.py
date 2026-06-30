"""Per-user asset-bundle CRUD for the lower-third-brand template.

A bundle is a directory at <uploads_dir>/<owner>/<bundle_id>/ holding named PNGs
the template already references (bottom-bar.png, watermark.png). The filenames
are fixed by the template contract, so only metadata is stored in the DB row.
"""
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlmodel import Session, select

from app.db import engine
from app.models import AssetBundle

# The PNG slots a lower-third-brand bundle must supply, keyed by the filename
# the template references. These are the contract.
BUNDLE_SLOTS = ("bottom-bar.png", "watermark.png")

# Validate uploads by PNG magic bytes — don't trust the client filename/extension.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class BundleError(ValueError):
    """Raised on invalid bundle input (bad file type, missing slot, etc.)."""


def _is_png(data: bytes) -> bool:
    return data[:8] == _PNG_MAGIC


def _bundle_root(uploads_dir: str, owner: str, bundle_id: str) -> Path:
    return Path(uploads_dir) / owner / bundle_id


def list_bundles(owner_username: str) -> list[AssetBundle]:
    with Session(engine) as s:
        stmt = (select(AssetBundle)
                .where(AssetBundle.owner_username == owner_username)
                .order_by(AssetBundle.created_at.desc()))  # type: ignore[union-attr]
        return list(s.exec(stmt).all())


def get_bundle(bundle_id: str, owner_username: str) -> AssetBundle | None:
    with Session(engine) as s:
        b = s.get(AssetBundle, bundle_id)
        if b is None or b.owner_username != owner_username:
            return None
        return b


def bundle_assets_dir(bundle_id: str, owner_username: str, uploads_dir: str) -> Path | None:
    """Return the on-disk directory holding a bundle's PNGs, or None if the
    bundle doesn't exist / isn't owned by the caller."""
    b = get_bundle(bundle_id, owner_username)
    if b is None:
        return None
    return _bundle_root(uploads_dir, owner_username, bundle_id)


def create_bundle(
    *, owner_username: str, name: str,
    bottom_bar: UploadFile, watermark: UploadFile,
    uploads_dir: str,
) -> AssetBundle:
    """Create a bundle: validate both PNGs, write them to disk, insert the row."""
    label = (name or "").strip() or "Untitled brand kit"
    files = {"bottom-bar.png": bottom_bar, "watermark.png": watermark}
    contents: dict[str, bytes] = {}
    for slot, upload in files.items():
        data = upload.file.read() if upload.file else b""
        if not data:
            raise BundleError(f"Missing file for slot '{slot}'")
        if not _is_png(data):
            raise BundleError(f"'{slot}' must be a PNG image")
        contents[slot] = data

    bundle_id = uuid.uuid4().hex
    bdir = _bundle_root(uploads_dir, owner_username, bundle_id)
    bdir.mkdir(parents=True, exist_ok=True)
    for slot, data in contents.items():
        (bdir / slot).write_bytes(data)

    bundle = AssetBundle(bundle_id=bundle_id, owner_username=owner_username, name=label)
    with Session(engine) as s:
        s.add(bundle)
        s.commit()
        s.refresh(bundle)
    return bundle


def delete_bundle(bundle_id: str, owner_username: str, uploads_dir: str) -> bool:
    """Delete a bundle's DB row and its on-disk directory. Returns False if the
    bundle isn't owned by the caller (so the caller can 404)."""
    with Session(engine) as s:
        b = s.get(AssetBundle, bundle_id)
        if b is None or b.owner_username != owner_username:
            return False
        s.delete(b)
        s.commit()
    # Remove the directory; ignore if it's already gone.
    bdir = _bundle_root(uploads_dir, owner_username, bundle_id)
    shutil.rmtree(bdir, ignore_errors=True)
    return True
