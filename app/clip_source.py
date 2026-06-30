"""Source short meme clips from Giphy or Klipy."""
from pathlib import Path

import httpx

from app.models import ClipInfo


def fetch_clip(
    *, query: str, source: str, api_key: str, dest_dir: str
) -> ClipInfo:
    if source == "giphy":
        return _fetch_giphy(query, api_key, dest_dir)
    if source == "klipy":
        return _fetch_klipy(query, api_key, dest_dir)
    raise ValueError(f"Unknown source '{source}' (use 'giphy' or 'klipy')")


def _fetch_giphy(query: str, api_key: str, dest_dir: str) -> ClipInfo:
    url = "https://api.giphy.com/v1/gifs/search"
    resp = httpx.get(
        url,
        params={"api_key": api_key, "q": query, "limit": 5, "rating": "pg"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", [])
    if not items:
        raise LookupError(f"Giphy returned no clips for '{query}'")
    images = items[0]["images"]
    # Prefer the HD variant (1080p) when present; fall back to original.
    # `original` is often only 480p and looks pixelated when upscaled to 1080.
    chosen = images.get("hd") or images["original"]
    return _download(
        mp4_url=chosen["mp4"],
        source="giphy",
        width=int(chosen.get("width") or 0) or None,
        height=int(chosen.get("height") or 0) or None,
        dest_dir=dest_dir,
    )


def _fetch_klipy(query: str, api_key: str, dest_dir: str) -> ClipInfo:
    url = "https://api.klipy.com/api/meme/search"
    resp = httpx.get(
        url, params={"api_key": api_key, "q": query}, timeout=15
    )
    resp.raise_for_status()
    body = resp.json()
    items = body.get("data") or body.get("results") or []
    if not items:
        raise LookupError(f"Klipy returned no clips for '{query}'")
    item = items[0]
    # Klipy nests mp4 under media.formats; tolerate shape differences.
    mp4_url = (
        item.get("media", {}).get("formats", {}).get("mp4", {}).get("url")
        or item.get("mp4")
    )
    if not mp4_url:
        raise LookupError(f"Klipy item had no mp4 url: {item}")
    return _download(
        mp4_url=mp4_url,
        source="klipy",
        width=item.get("width"),
        height=item.get("height"),
        dest_dir=dest_dir,
    )


def _download(
    *, mp4_url: str, source: str, width, height, dest_dir: str
) -> ClipInfo:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    file_resp = httpx.get(mp4_url, timeout=30, follow_redirects=True)
    file_resp.raise_for_status()
    out_path = dest / f"clip_{source}.mp4"
    out_path.write_bytes(file_resp.content)
    return ClipInfo(
        path=str(out_path),
        source=source,
        original_url=mp4_url,
        width=width,
        height=height,
    )
