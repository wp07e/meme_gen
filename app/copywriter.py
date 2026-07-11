"""Generate caption/hook/overlay text via OpenRouter (OpenAI-compatible)."""
import json
import re

from openai import OpenAI

from app.models import CopyResult

SYSTEM_PROMPT = """You write punchy meme captions for short videos.
Return ONLY a JSON object, no prose, with these exact keys:
- "caption": one string, a post caption for social media (1-2 hashtags, max 200 chars)
- "hook": one string, a short on-screen hook (max 6 words)
- "overlay_lines": a JSON array containing EXACTLY {n} short text strings (NOT characters).
  Each string is a COMPLETE PHRASE of max 4 words, e.g. ["Me on Monday", "Also me"].
  NEVER split a word into single characters. NEVER return a single string for this field.
Topic: {topic}. Tone: {tone}."""


def _extract_json(text: str) -> dict:
    # Tolerate ```json fenced blocks or raw JSON.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model response: {text!r}")
    return json.loads(match.group(0))


def generate_copy(
    *,
    topic: str,
    tone: str,
    overlay_slot_count: int,
    api_key: str,
    model: str,
    base_url: str = "https://openrouter.ai/api/v1",
) -> CopyResult:
    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = SYSTEM_PROMPT.format(n=overlay_slot_count, topic=topic, tone=tone)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Write copy for: {topic}"},
        ],
        temperature=0.9,
        max_tokens=600,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("Model returned empty content.")
    data = _extract_json(content)
    return CopyResult(
        caption=str(data["caption"]).strip(),
        hook=str(data["hook"]).strip(),
        overlay_lines=_normalize_overlay_lines(data.get("overlay_lines")),
    )


def _normalize_overlay_lines(raw) -> list[str]:
    """Defensively coerce the model's overlay_lines into a list of phrases.

    Models sometimes return a bare string instead of an array, or spell words
    out character-by-character. Normalize both into proper phrases.
    """
    # Bare string -> wrap in a single-element list (don't let list(str) split chars).
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"overlay_lines must be an array of strings, got {type(raw)}")

    # Detect the char-split failure BEFORE stripping (spaces are real chars here):
    # many single-or-double-char elements that concatenate into readable text.
    str_items = [str(i) for i in raw]
    if len(str_items) >= 3 and all(len(s) <= 2 for s in str_items):
        merged = "".join(str_items)
        merged = " ".join(merged.split()).strip()  # collapse runs of whitespace
        if merged:
            return [merged]

    # Normal case: strip and drop empties.
    lines = [s.strip() for s in str_items if s and s.strip()]
    if not lines:
        raise ValueError("overlay_lines was empty after normalization.")
    return lines


def suggest_keywords(
    *, query: str, api_key: str, model: str,
    base_url: str = "https://openrouter.ai/api/v1", count: int = 3,
) -> list[str]:
    """Ask AI for alternative search keywords for a meme clip search.

    Used by the retry loop when truncation has already been tried. Returns up to
    `count` short, lowercase keyword phrases suitable for Giphy/Klipy search.
    """
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": (
                "You suggest alternative search keywords for finding meme clips. "
                f"Return ONLY a JSON object: {{\"keywords\": [\"{count} short phrases\"]}}. "
                "Each phrase is 1-3 words, lowercase, no quotes. No prose."
            )},
            {"role": "user", "content": f"Original search: {query}\nSuggest {count} alternatives."},
        ],
        temperature=0.9,
        max_tokens=300,
    )
    content = response.choices[0].message.content or ""
    data = _extract_json(content)
    kws = [str(k).strip().lower() for k in data.get("keywords", []) if str(k).strip()]
    return kws[:count]
