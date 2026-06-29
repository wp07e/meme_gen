"""Generate caption/hook/overlay text via Moonshot Kimi (OpenAI-compatible)."""
import json
import re

from openai import OpenAI

from app.models import CopyResult

SYSTEM_PROMPT = """You write punchy meme captions for short videos.
Return ONLY a JSON object, no prose, with keys:
- "caption": a post caption for social media (include 1-2 hashtags, max 200 chars)
- "hook": a short on-screen hook (max 6 words)
- "overlay_lines": exactly {n} short text lines for the video overlay (max 4 words each)
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
    base_url: str = "https://api.moonshot.ai/v1",
) -> CopyResult:
    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = SYSTEM_PROMPT.format(n=overlay_slot_count, topic=topic, tone=tone)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Write copy for: {topic}"},
        ],
        # Reasoning models (kimi-k2.6) require temperature=1 and spend
        # thousands of tokens thinking before the visible answer; budget generously.
        temperature=1,
        max_tokens=4000,
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
        caption=data["caption"],
        hook=data["hook"],
        overlay_lines=list(data["overlay_lines"]),
    )
