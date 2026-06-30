"""Source meme clips from Giphy or Klipy, with quality gating.

Two layers:
- search_*(): hit an API, return a list of ClipInfo candidates (NOT downloaded yet).
- download(): fetch the chosen clip's bytes to disk.

The orchestrating retry loop (fetch_best_clip) lives here too but is the job of
Milestone 3. For Milestone 2 we fix Klipy and add meets_quality.
"""
from pathlib import Path

import httpx

from app.models import ClipInfo


# Klipy base + URL pattern (app_key in PATH, not query — this was the crash bug).
KLIPY_BASE = "https://api.klipy.com/api/v1"

# Giphy search endpoint.
GIPHY_SEARCH = "https://api.giphy.com/v1/gifs/search"


class RateLimitError(Exception):
    """Provider returned 429 — caller should skip this provider."""


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

# Accept a clip if its best mp4 has short edge >= this AND file size >= this.
# 480px short edge = IG/FB minimum recommended upload dimension for clips;
# below it the upscale to 1080 visibly degrades on phone displays.
MIN_SHORT_EDGE = 480
MIN_FILE_BYTES = 150_000


def meets_quality(clip: ClipInfo) -> bool:
    """True if the clip is sharp enough for IG/FB feeds (no pixelation)."""
    if clip.short_edge < MIN_SHORT_EDGE:
        return False
    if (clip.size_bytes or 0) < MIN_FILE_BYTES:
        return False
    return True


# ---------------------------------------------------------------------------
# Giphy search
# ---------------------------------------------------------------------------

def search_giphy(*, query: str, api_key: str, limit: int = 8) -> list[ClipInfo]:
    """Return candidate clips (no download). Prefers HD variant metadata."""
    resp = httpx.get(
        GIPHY_SEARCH,
        params={"api_key": api_key, "q": query, "limit": limit, "rating": "pg"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("data", [])
    candidates: list[ClipInfo] = []
    for item in items:
        images = item.get("images", {})
        # Prefer HD; fall back to original.
        chosen = images.get("hd") or images.get("original")
        if not chosen or not chosen.get("mp4"):
            continue
        candidates.append(ClipInfo(
            path="",  # filled by download()
            source="giphy",
            category="gifs",
            original_url=chosen["mp4"],
            width=int(chosen.get("width") or 0) or None,
            height=int(chosen.get("height") or 0) or None,
            size_bytes=int(chosen.get("mp4_size") or 0) or None,
        ))
    return candidates


# ---------------------------------------------------------------------------
# Klipy search — CORRECT endpoint (was the crash bug)
# ---------------------------------------------------------------------------

def search_klipy(
    *, query: str, app_key: str, category: str, customer_id: str = "meme_gen",
    limit: int = 8,
) -> list[ClipInfo]:
    """Search Klipy clips or gifs. category: 'clips' | 'gifs'.

    URL pattern: /api/v1/{app_key}/{category}/search?q=... (app_key in PATH).
    Header: Content-Type: application/json.
    """
    url = f"{KLIPY_BASE}/{app_key}/{category}/search"
    resp = httpx.get(
        url,
        params={
            "q": query, "per_page": limit,
            "customer_id": customer_id, "locale": "us", "content_filter": "high",
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    if resp.status_code == 429:
        raise RateLimitError(f"Klipy rate-limited (429) for {category}/search")
    resp.raise_for_status()
    body = resp.json()
    items = body.get("data", {}).get("data", []) or []

    candidates: list[ClipInfo] = []
    for item in items:
        clip = _parse_klipy_item(item, category)
        if clip:
            candidates.append(clip)
    return candidates


def _parse_klipy_item(item: dict, category: str) -> ClipInfo | None:
    """Extract a ClipInfo from one Klipy result item.

    Clips: file.mp4 (string URL) + file_meta.mp4.{width,height,size}
    GIFs:  file.{hd,md,sm,xs}.mp4.{url,width,height,size} — prefer hd.
    """
    file_obj = item.get("file", {})
    if category == "clips":
        mp4_url = file_obj.get("mp4")
        if not mp4_url:
            return None
        meta = (item.get("file_meta") or {}).get("mp4") or {}
        return ClipInfo(
            path="", source="klipy", category="clips",
            original_url=mp4_url,
            width=meta.get("width"),
            height=meta.get("height"),
            size_bytes=meta.get("size"),
        )
    else:  # gifs — prefer hd, fall back to md
        for tier in ("hd", "md", "sm"):
            tier_obj = file_obj.get(tier) or {}
            mp4 = tier_obj.get("mp4") or {}
            url = mp4.get("url")
            if url:
                return ClipInfo(
                    path="", source="klipy", category="gifs",
                    original_url=url,
                    width=mp4.get("width"),
                    height=mp4.get("height"),
                    size_bytes=mp4.get("size"),
                )
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_clip(*, clip: ClipInfo, dest_dir: str) -> ClipInfo:
    """Download the clip's bytes to dest_dir, return a new ClipInfo with path set."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    file_resp = httpx.get(clip.original_url, timeout=30, follow_redirects=True)
    file_resp.raise_for_status()
    content = file_resp.content
    out_path = dest / f"clip_{clip.source}_{clip.category}_{abs(hash(clip.original_url))}.mp4"
    out_path.write_bytes(content)
    # Update size if we didn't have it from metadata.
    size = clip.size_bytes or len(content)
    return clip.model_copy(update={"path": str(out_path), "size_bytes": size})


# ---------------------------------------------------------------------------
# Legacy single-shot fetch (kept for backward-compat / simple tests)
# ---------------------------------------------------------------------------

def fetch_clip(*, query: str, source: str, api_key: str, dest_dir: str) -> ClipInfo:
    """Quick single-provider fetch (no quality gate, no dedupe). Legacy path."""
    if source == "giphy":
        candidates = search_giphy(query=query, api_key=api_key)
        if not candidates:
            raise LookupError(f"Giphy returned no clips for '{query}'")
        return download_clip(clip=candidates[0], dest_dir=dest_dir)
    if source == "klipy":
        candidates = search_klipy(query=query, app_key=api_key, category="clips") \
                  or search_klipy(query=query, app_key=api_key, category="gifs")
        if not candidates:
            raise LookupError(f"Klipy returned no clips for '{query}'")
        return download_clip(clip=candidates[0], dest_dir=dest_dir)
    raise ValueError(f"Unknown source '{source}' (use 'giphy' or 'klipy')")
