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

# Resolution + size: apply to ALL candidates (clips and GIFs).
# 480px short edge = IG/FB minimum recommended upload dimension;
# below it the upscale to 1080 visibly degrades on phone displays.
MIN_SHORT_EDGE = 480
MIN_FILE_BYTES = 150_000

# Duration: clips must be 5-15s (per user spec). GIFs accept any length.
CLIP_MIN_DURATION = 5.0
CLIP_MAX_DURATION = 15.0


def meets_quality(clip: ClipInfo) -> bool:
    """Resolution + size gate (format-agnostic). Returns False if too small."""
    if clip.short_edge < MIN_SHORT_EDGE:
        return False
    if (clip.size_bytes or 0) < MIN_FILE_BYTES:
        return False
    return True


def meets_duration(clip: ClipInfo) -> bool:
    """Duration gate — only applies to clips, not GIFs.

    Clips must be 5-15s. GIFs (category 'gifs') accept any length since they
    loop natively and are meant to be short. Requires clip.duration to be probed.
    """
    if not clip.is_clip:
        return True  # GIFs are exempt
    if clip.duration is None:
        return False  # clip duration not yet probed — treat as failing
    return CLIP_MIN_DURATION <= clip.duration <= CLIP_MAX_DURATION


def probe_duration(clip: ClipInfo) -> ClipInfo:
    """Download the candidate, ffprobe its duration, return an updated ClipInfo.

    Only call this for clip-format candidates (GIFs skip the duration gate).
    Downloads the full file (~1s) — reliable but adds latency per probe.
    """
    import subprocess
    import tempfile
    import os
    resp = httpx.get(clip.original_url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", tmp_path],
            capture_output=True, text=True, check=True,
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0
    finally:
        os.unlink(tmp_path)
    return clip.model_copy(update={"duration": dur, "size_bytes": clip.size_bytes or len(resp.content)})


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


# ---------------------------------------------------------------------------
# The retry loop: rotate providers, dedupe via DB, quality gate, query mutation
# ---------------------------------------------------------------------------

PROVIDERS = ("giphy", "klipy")
MAX_KLIPY_ATTEMPTS_PER_JOB = 5  # docs: 100 req/hr testing mode — cap usage


class CancelledError(Exception):
    """User pressed cancel during the search loop."""


def fetch_best_clip(
    *,
    query: str,
    format_pref,  # FormatPref
    rotate_start: str,  # "giphy" | "klipy" — which provider to try first
    giphy_key: str,
    klipy_key: str,
    klipy_customer_id: str,
    session_id: str,
    session,  # SQLModel Session (for dedupe reads)
    dest_dir: str,
    on_attempt,  # callable(str) -> None — report progress
    is_cancelled,  # callable() -> bool
    suggest_keywords_fn=None,  # callable(query) -> list[str] (Moonshot), optional
    max_attempts: int = 20,
) -> ClipInfo:
    """Search providers in rotation, skipping seen clips and low-quality ones.

    On finding a good, unseen clip, downloads and returns it. Raises CancelledError
    if the user cancels, LookupError if nothing acceptable is found after all attempts.
    """
    providers = list(PROVIDERS)
    if rotate_start == "klipy":
        providers = ["klipy", "giphy"]

    current_query = query
    klipy_attempts = 0
    attempt = 0
    round_num = 0
    mutation_pool: list[str] = []  # LLM-suggested alternatives

    while attempt < max_attempts:
        if is_cancelled():
            raise CancelledError()
        made_an_attempt_this_round = False

        for provider in providers:
            for category in _categories_for(format_pref, provider):
                if is_cancelled():
                    raise CancelledError()
                # Respect Klipy rate cap.
                if provider == "klipy" and klipy_attempts >= MAX_KLIPY_ATTEMPTS_PER_JOB:
                    on_attempt(f"Skipping Klipy (rate cap {MAX_KLIPY_ATTEMPTS_PER_JOB} reached).")
                    continue
                attempt += 1
                made_an_attempt_this_round = True
                on_attempt(f"Searching {provider} {category} for '{current_query}' (try {attempt}/{max_attempts})")
                try:
                    candidates = _search_provider(
                        provider=provider, category=category, query=current_query,
                        giphy_key=giphy_key, klipy_key=klipy_key,
                        klipy_customer_id=klipy_customer_id,
                    )
                except RateLimitError as e:
                    on_attempt(f"  {provider} rate-limited, skipping: {e}")
                    continue
                except Exception as e:
                    on_attempt(f"  {provider} {category} error: {type(e).__name__}")
                    continue
                if provider == "klipy":
                    klipy_attempts += 1

                for cand in candidates:
                    if is_cancelled():
                        raise CancelledError()
                    if _is_seen(cand.original_url, session_id, session):
                        on_attempt(f"  already used this session, skipping")
                        continue
                    if not meets_quality(cand):
                        on_attempt(f"  low quality ({cand.short_edge}px, {cand.size_bytes}B), will retry")
                        continue
                    # Clips must pass the duration gate (5-15s). GIFs skip it.
                    # Probing downloads the file (~1s) — only for clip candidates.
                    if cand.is_clip:
                        try:
                            on_attempt(f"  checking length of {provider} {category} clip…")
                            cand = probe_duration(cand)
                        except Exception as e:
                            on_attempt(f"  duration probe failed: {e}")
                            continue
                        if not meets_duration(cand):
                            on_attempt(f"  wrong length ({cand.duration:.1f}s; need {CLIP_MIN_DURATION}-{CLIP_MAX_DURATION}s), will retry")
                            continue
                    # Accept — download and return.
                    dur_info = f", {cand.duration:.1f}s" if cand.duration else ""
                    on_attempt(f"  ✓ accepted {provider} {category} ({cand.short_edge}px{dur_info})")
                    return download_clip(clip=cand, dest_dir=dest_dir)

        # Exhausted all providers/categories for current_query → mutate the query.
        round_num += 1
        current_query = _next_query(
            base_query=query, current=current_query, round_num=round_num,
            mutation_pool=mutation_pool, on_attempt=on_attempt,
            suggest_keywords_fn=suggest_keywords_fn,
        )
        if not current_query:
            break
        on_attempt(f"No good clip yet. Retrying with modified search: '{current_query}'")

    raise LookupError(f"No acceptable clip found after {attempt} attempts.")


def _categories_for(format_pref, provider: str) -> list[str]:
    """Which Klipy/Giphy categories to try, given format preference."""
    if provider == "giphy":
        return ["gifs"]
    # klipy
    from app.models import FormatPref
    if format_pref == FormatPref.gif:
        return ["gifs"]
    if format_pref == FormatPref.clip:
        return ["clips"]
    return ["clips", "gifs"]  # auto: clips first, gif fallback


def _search_provider(*, provider, category, query, giphy_key, klipy_key, klipy_customer_id) -> list[ClipInfo]:
    if provider == "giphy":
        return search_giphy(query=query, api_key=giphy_key)
    # klipy
    return search_klipy(query=query, app_key=klipy_key, category=category,
                        customer_id=klipy_customer_id)


def _is_seen(url: str, session_id: str, session) -> bool:
    from sqlmodel import select
    from app.models import SeenClip
    found = session.exec(
        select(SeenClip).where(SeenClip.session_id == session_id, SeenClip.url == url)
    ).first()
    return found is not None


def _next_query(*, base_query, current, round_num, mutation_pool, on_attempt, suggest_keywords_fn) -> str:
    """Return the next query to try. Rounds 1-2: drop trailing words. Round 3+: LLM synonyms."""
    words = current.split()
    if round_num <= 2 and len(words) > 1:
        # Drop one trailing word each round.
        return " ".join(words[:-1])

    # Rounds 3+: draw from LLM-suggested synonyms (lazy-populate once).
    if suggest_keywords_fn is not None and not mutation_pool:
        try:
            on_attempt("  Asking AI for alternative search keywords…")
            mutation_pool.extend(suggest_keywords_fn(base_query))
        except Exception as e:
            on_attempt(f"  keyword suggestion failed: {e}")
    if mutation_pool:
        return mutation_pool.pop(0)

    # Nothing left to try — keep shortening if possible, else give up.
    if len(words) > 1:
        return " ".join(words[:-1])
    return ""

