"""Generate caption/hook/overlay text via Moonshot Kimi (OpenAI-compatible)."""
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


def _is_reasoning_model(model: str) -> bool:
    """Reasoning models (kimi-k2.*) only allow temperature=1."""
    return model.lower().startswith("kimi-k2")


def generate_copy(
    *,
    topic: str,
    tone: str,
    overlay_slot_count: int,
    api_key: str,
    model: str,
    base_url: str = "https://api.moonshot.ai/v1",
) -> CopyResult:
    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = SYSTEM_PROMPT.format(n=overlay_slot_count, topic=topic, tone=tone)
    reasoning = _is_reasoning_model(model)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Write copy for: {topic}"},
        ],
        # Reasoning models (kimi-k2.*) require temperature=1 and spend thousands
        # of tokens thinking before the visible answer; budget generously.
        # Non-reasoning models (moonshot-v1-*) accept the full range and produce
        # better creative copy at 0.9.
        temperature=1 if reasoning else 0.9,
        max_tokens=4000 if reasoning else 600,
    )
    message = response.choices[0].message
    content = message.content or ""
    # Some reasoning models return the answer in reasoning_content; fall back
    # to it only if the visible content is empty.
    if not content.strip():
        content = getattr(message, "reasoning_content", "") or ""
    if not content.strip():
        raise ValueError("Model returned empty content and reasoning_content.")
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
