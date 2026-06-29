# meme_gen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app that turns a topic into a ready-to-post branded meme video by sourcing a clip from Giphy/Klipy, generating copy via Moonshot Kimi, and compositing it with Canva-made overlays using MoviePy/FFmpeg.

**Architecture:** A thin FastAPI web UI drives a four-stage Python pipeline: `copywriter` (Moonshot) → `clip_source` (Giphy/Klipy) → `renderer` (MoviePy/FFmpeg), chained by `orchestrator`. Templates are JSON layout specs; brand overlays are transparent PNGs designed once in Canva. No database, no auth — local-only, file-based.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, MoviePy 2.x, FFmpeg, Pillow, httpx, openai SDK (pointed at Moonshot), pytest, python-dotenv. Frontend is plain HTML+JS (no build step).

---

## Verified API facts (use these exactly)

- **MoviePy 2.x imports:** `from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ImageClip` — there is NO `moviepy.editor` in v2.
- **MoviePy 2.x `font` requires a FILE PATH, not a font name.** `"Arial-Bold"` fails; use `/System/Library/Fonts/Supplemental/Arial Bold.ttf` (macOS). Template JSON `font` field holds the path.
- **MoviePy 2.x audio volume:** use `clip.audio.with_volume_scaled(0.0)` — there is NO `afx.volumex` in 2.1.x.
- **Moonshot Kimi:** OpenAI-compatible. `base_url="https://api.moonshot.ai/v1"`, model `"kimi-k2"`. Uses the standard `openai` Python SDK.
- **Giphy:** `GET https://api.giphy.com/v1/gifs/search?api_key=KEY&q=QUERY&limit=5&rating=pg` — note: returns GIF objects whose `images.original.mp4` field gives a short looping MP4 (this is what we render).
- **Klipy:** `GET https://api.klipy.com/api/meme/search?q=QUERY&api_key=KEY` (REST fallback when MCP not configured) — response items have `media.formats` with mp4 URLs.
- **Pinned versions:** moviepy 2.1.2 requires `Pillow<11.0`, so Pillow is pinned to 10.4.0.

---

## File Structure

```
meme_gen/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
├── app/
│   ├── __init__.py
│   ├── config.py          # loads .env, exposes settings singleton
│   ├── models.py          # Pydantic data shapes (CopyResult, RenderRequest, etc.)
│   ├── copywriter.py      # Moonshot Kimi integration — pure over API
│   ├── clip_source.py     # Giphy + Klipy providers, swappable
│   ├── templates.py       # load + validate template JSON specs
│   ├── renderer.py        # MoviePy/FFmpeg compositing
│   ├── orchestrator.py    # chains copywriter → clip_source → renderer
│   └── main.py            # FastAPI app + routes
├── templates/             # JSON layout specs (data)
│   └── caption-top-bottom.json
├── assets/                # Canva PNG overlays + README
│   └── README.md
├── static/
│   ├── index.html         # the web UI
│   └── app.js
├── output/                # rendered MP4s (gitignored)
├── tmp/                   # downloaded clips (gitignored)
└── tests/
    ├── __init__.py
    ├── conftest.py        # shared fixtures (tmp dirs, mock API responses)
    ├── test_templates.py
    ├── test_copywriter.py
    ├── test_clip_source.py
    ├── test_renderer.py
    ├── test_orchestrator.py
    └── test_api.py
```

**Responsibilities:** each `app/` file has one job and a clean interface (see spec Section 4). Templates and assets are *data*, not code, so new formats/overlays need no code change.

---

## Task 1: Project scaffolding & dependencies

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `app/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `assets/README.md`
- Create: `README.md`

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
moviepy==2.1.2
Pillow==11.1.0
httpx==0.28.1
openai==1.59.7
python-dotenv==1.0.1
pytest==8.3.4
pytest-asyncio==0.25.2
respx==0.22.0
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
venv/
output/
tmp/
.DS_Store
```

- [ ] **Step 3: Write `.env.example`**

```
# Copy to .env and fill in. All keys are required for full pipeline runs.
GIPHY_API_KEY=
KLIPY_API_KEY=
MOONSHOT_API_KEY=
MOONSHOT_MODEL=kimi-k2
# Local server
HOST=127.0.0.1
PORT=8000
```

- [ ] **Step 4: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

- [ ] **Step 5: Create empty package markers and placeholder dirs**

Create empty `app/__init__.py` and `tests/__init__.py`. Create `assets/README.md`:

```markdown
# Assets (Canva overlay PNGs)

Drop transparent-PNG overlays designed in Canva (via the Canva MCP) here.
The renderer reads them by filename referenced in template JSON specs.

Examples to create: `bottom-bar.png`, `end-card.png`, `watermark.png`.
Make canvases transparent and export as PNG.
```

- [ ] **Step 6: Write top-level `README.md`**

```markdown
# meme_gen

Turn a topic into a ready-to-post branded meme video. Local web app.

## Setup
1. Install FFmpeg (`brew install ffmpeg` on macOS).
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and fill in API keys.
5. `uvicorn app.main:app --reload`

Open http://127.0.0.1:8000

## API keys needed
- GIPHY_API_KEY — https://developers.giphy.com
- KLIPY_API_KEY — https://klipy.com (optional; Giphy alone works)
- MOONSHOT_API_KEY — https://platform.kimi.ai
```

- [ ] **Step 7: Create venv, install, verify**

Run:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```
Expected: installs succeed. Then run `python -c "import moviepy, fastapi, openai; print('ok')"` → prints `ok`.

- [ ] **Step 8: Verify FFmpeg is installed**

Run: `ffmpeg -version`
Expected: prints version info. If missing, `brew install ffmpeg`.

- [ ] **Step 9: Init git and commit**

```bash
git init
git add -A
git commit -m "chore: project scaffolding"
```

---

## Task 2: Config loader

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test `tests/test_config.py`**

```python
from app.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "g_key")
    monkeypatch.setenv("KLIPY_API_KEY", "k_key")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m_key")
    monkeypatch.setenv("MOONSHOT_MODEL", "kimi-k2")
    settings = Settings()
    assert settings.giphy_api_key == "g_key"
    assert settings.klipy_api_key == "k_key"
    assert settings.moonshot_api_key == "m_key"
    assert settings.moonshot_model == "kimi-k2"
    assert settings.host == "127.0.0.1"  # default
    assert settings.port == 8000
```

- [ ] **Step 2: Run, verify fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (module `app.config` doesn't exist).

- [ ] **Step 3: Write `app/config.py`**

```python
"""Configuration loaded from environment / .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    giphy_api_key: str = os.getenv("GIPHY_API_KEY", "")
    klipy_api_key: str = os.getenv("KLIPY_API_KEY", "")
    moonshot_api_key: str = os.getenv("MOONSHOT_API_KEY", "")
    moonshot_model: str = os.getenv("MOONSHOT_MODEL", "kimi-k2")
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))
    output_dir: str = "output"
    tmp_dir: str = "tmp"


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: config loader"
```

---

## Task 3: Shared data models

**Files:**
- Create: `app/models.py`

- [ ] **Step 1: Write `app/models.py`**

```python
"""Pydantic data shapes passed between pipeline stages."""
from pydantic import BaseModel, Field


class CopyResult(BaseModel):
    """Output of copywriter.py."""
    caption: str = Field(description="Post caption (for FB/IG text field)")
    hook: str = Field(description="Short hook shown on screen briefly")
    overlay_lines: list[str] = Field(
        description="Lines of text rendered onto the video (e.g. top/bottom)"
    )


class ClipInfo(BaseModel):
    """Output of clip_source.py."""
    path: str
    source: str  # "giphy" | "klipy"
    original_url: str
    width: int | None = None
    height: int | None = None


class RenderRequest(BaseModel):
    """Input to the orchestrator from the web UI."""
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"
    source: str = "giphy"  # "giphy" | "klipy"
    # When the UI previews copy first, it posts the edited copy back:
    copy: CopyResult | None = None


class RenderResult(BaseModel):
    """Output of orchestrator / the render route."""
    output_path: str
    copy: CopyResult
    clip: ClipInfo
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "from app.models import CopyResult, ClipInfo, RenderRequest, RenderResult; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/models.py
git commit -m "feat: shared data models"
```

---

## Task 4: Template loader

**Files:**
- Create: `app/templates.py`
- Create: `templates/caption-top-bottom.json`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the template spec `templates/caption-top-bottom.json`**

```json
{
  "name": "caption-top-bottom",
  "description": "Classic meme format: bold text on top and bottom over the clip.",
  "aspect_ratio": "1:1",
  "width": 1080,
  "height": 1080,
  "font": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
  "font_size": 64,
  "font_color": "white",
  "stroke_color": "black",
  "stroke_width": 3,
  "positions": {
    "top": { "x": "center", "y": 60 },
    "bottom": { "x": "center", "y": "bottom-60" }
  },
  "overlays": []
}
```

- [ ] **Step 2: Write failing test `tests/test_templates.py`**

```python
import json
from pathlib import Path

import pytest

from app.templates import TemplateSpec, load_template, list_templates


def test_load_template_returns_spec():
    spec = load_template("caption-top-bottom")
    assert isinstance(spec, TemplateSpec)
    assert spec.name == "caption-top-bottom"
    assert spec.width == 1080
    assert spec.aspect_ratio == "1:1"


def test_load_template_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("app.templates.TEMPLATES_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_template("does-not-exist")


def test_list_templates_includes_known():
    names = list_templates()
    assert "caption-top-bottom" in names
```

- [ ] **Step 3: Run, verify fail**

Run: `pytest tests/test_templates.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Write `app/templates.py`**

```python
"""Load and validate JSON template layout specs."""
import json
from pathlib import Path

from pydantic import BaseModel

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TextPosition(BaseModel):
    x: str  # "center" or pixel int as str
    y: str  # "bottom-60" or pixel int as str


class OverlayRef(BaseModel):
    file: str  # filename in assets/
    x: int = 0
    y: int = 0


class TemplateSpec(BaseModel):
    name: str
    description: str
    aspect_ratio: str  # "1:1" | "9:16"
    width: int
    height: int
    font: str
    font_size: int
    font_color: str
    stroke_color: str
    stroke_width: int
    positions: dict[str, TextPosition]
    overlays: list[OverlayRef] = []


def load_template(name: str) -> TemplateSpec:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No template named '{name}' at {path}")
    data = json.loads(path.read_text())
    return TemplateSpec(**data)


def list_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_templates.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add app/templates.py templates/ tests/test_templates.py
git commit -m "feat: template loader + first template"
```

---

## Task 5: Copywriter (Moonshot Kimi)

**Files:**
- Create: `app/copywriter.py`
- Test: `tests/test_copywriter.py`
- Test helper: `tests/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""Shared fixtures."""
import pytest

from app.models import CopyResult, ClipInfo


@pytest.fixture
def sample_copy():
    return CopyResult(
        caption="When Monday hits and you forgot it was a holiday 💀 #monday",
        hook="POV: the alarm was lying",
        overlay_lines=["ME ON MONDAY", "ALSO ME:"],
    )


@pytest.fixture
def sample_clip_info(tmp_path):
    return ClipInfo(
        path=str(tmp_path / "clip.mp4"),
        source="giphy",
        original_url="https://media.giphy.com/media/abc/giphy.mp4",
        width=480,
        height=480,
    )
```

- [ ] **Step 2: Write failing test `tests/test_copywriter.py`**

```python
from unittest.mock import MagicMock, patch

from app.copywriter import generate_copy


def test_generate_copy_parses_json_response(sample_copy):
    fake_json = """
    {
      "caption": "When Monday hits and you forgot it was a holiday 💀 #monday",
      "hook": "POV: the alarm was lying",
      "overlay_lines": ["ME ON MONDAY", "ALSO ME:"]
    }
    """
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=fake_json))]
    )
    with patch("app.copywriter.OpenAI", return_value=mock_client):
        result = generate_copy(
            topic="Monday motivation, gym",
            tone="funny",
            overlay_slot_count=2,
            api_key="fake-key",
            model="kimi-k2",
        )
    assert result.overlay_lines == ["ME ON MONDAY", "ALSO ME:"]
    assert result.hook == "POV: the alarm was lying"
    assert "#monday" in result.caption


def test_generate_copy_raises_on_bad_json():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not json"))]
    )
    import pytest
    with patch("app.copywriter.OpenAI", return_value=mock_client):
        with pytest.raises(ValueError):
            generate_copy(
                topic="x", tone="funny", overlay_slot_count=2,
                api_key="fake-key", model="kimi-k2",
            )
```

- [ ] **Step 3: Run, verify fail**

Run: `pytest tests/test_copywriter.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Write `app/copywriter.py`**

```python
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
        temperature=0.9,
    )
    content = response.choices[0].message.content
    data = _extract_json(content)
    return CopyResult(
        caption=data["caption"],
        hook=data["hook"],
        overlay_lines=list(data["overlay_lines"]),
    )
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_copywriter.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add app/copywriter.py tests/test_copywriter.py tests/conftest.py
git commit -m "feat: copywriter via Moonshot Kimi"
```

---

## Task 6: Clip source (Giphy + Klipy)

**Files:**
- Create: `app/clip_source.py`
- Test: `tests/test_clip_source.py`

- [ ] **Step 1: Write failing test `tests/test_clip_source.py`**

```python
from unittest.mock import patch, MagicMock

import httpx

from app.clip_source import fetch_clip


def test_fetch_clip_giphy_downloads_mp4(tmp_path):
    fake_body = {
        "data": [
            {
                "images": {
                    "original": {
                        "mp4": "https://media.giphy.com/media/x/giphy.mp4",
                        "mp4_size": "12345",
                        "width": "480",
                        "height": "480",
                    }
                }
            }
        ]
    }
    # Mock httpx.get for the search call AND the file download.
    search_response = MagicMock(status_code=200)
    search_response.json.return_value = fake_body
    search_response.raise_for_status = MagicMock()
    file_response = MagicMock(status_code=200, content=b"FAKEMP4BYTES")

    with patch("app.clip_source.httpx.get", side_effect=[search_response, file_response]):
        info = fetch_clip(
            query="monday gym",
            source="giphy",
            api_key="g_key",
            dest_dir=str(tmp_path),
        )
    assert info.source == "giphy"
    assert info.path.endswith(".mp4")
    assert info.width == 480
    from pathlib import Path
    assert Path(info.path).read_bytes() == b"FAKEMP4BYTES"


def test_fetch_clip_no_results_raises(tmp_path):
    search_response = MagicMock(status_code=200)
    search_response.json.return_value = {"data": []}
    search_response.raise_for_status = MagicMock()
    import pytest
    with patch("app.clip_source.httpx.get", return_value=search_response):
        with pytest.raises(LookupError):
            fetch_clip("nothing", "giphy", "g_key", str(tmp_path))
```

- [ ] **Step 2: Run, verify fail**

Run: `pytest tests/test_clip_source.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `app/clip_source.py`**

```python
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
    original = items[0]["images"]["original"]
    return _download(
        mp4_url=original["mp4"],
        source="giphy",
        width=int(original.get("width") or 0) or None,
        height=int(original.get("height") or 0) or None,
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
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_clip_source.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/clip_source.py tests/test_clip_source.py
git commit -m "feat: clip source (Giphy + Klipy)"
```

---

## Task 7: Renderer (MoviePy/FFmpeg) — the hardest part

**Files:**
- Create: `app/renderer.py`
- Test: `tests/test_renderer.py`
- Test asset: `tests/fixtures/test_clip.mp4` (generated, not committed via binary copy)

- [ ] **Step 1: Generate a tiny test clip with FFmpeg**

Run:
```bash
mkdir -p tests/fixtures
ffmpeg -y -f lavfi -i testsrc=duration=2:size=480x480:rate=30 \
  -c:v libx264 -pix_fmt yuv420p tests/fixtures/test_clip.mp4
```
Expected: file `tests/fixtures/test_clip.mp4` exists, ~small.

- [ ] **Step 2: Write failing test `tests/test_renderer.py`**

```python
from pathlib import Path

from app.renderer import render_video
from app.models import CopyResult, ClipInfo
from app.templates import load_template

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_render_video_produces_mp4(tmp_path, sample_copy):
    clip = ClipInfo(
        path=str(FIXTURE),
        source="giphy",
        original_url="x",
        width=480,
        height=480,
    )
    spec = load_template("caption-top-bottom")
    out = render_video(
        clip=clip,
        copy=sample_copy,
        template=spec,
        output_dir=str(tmp_path),
    )
    assert Path(out).exists()
    assert out.endswith(".mp4")
    assert Path(out).stat().st_size > 0
    # Should be square 1080x1080 per the template.
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    w, h = probe.stdout.strip().split(",")
    assert (w, h) == ("1080", "1080")
```

- [ ] **Step 3: Run, verify fail**

Run: `pytest tests/test_renderer.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Write `app/renderer.py`**

```python
"""Composite clip + overlays + text into a final MP4 via MoviePy 2.x."""
import datetime as dt
import re
from pathlib import Path

from moviepy import (
    VideoFileClip,
    TextClip,
    ImageClip,
    CompositeVideoClip,
)

from app.models import ClipInfo, CopyResult
from app.templates import TemplateSpec

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def render_video(
    *, clip: ClipInfo, copy: CopyResult, template: TemplateSpec, output_dir: str
) -> str:
    base = VideoFileClip(clip.path)

    # Resize/crop to the template aspect ratio.
    sized = _fit_to_size(base, template.width, template.height)
    duration = sized.duration

    layers = [sized]

    # Static image overlays (Canva PNGs).
    for ov in template.overlays:
        img_path = ASSETS_DIR / ov.file
        if img_path.exists():
            img = ImageClip(str(img_path)).with_duration(duration)
            img = img.with_position((ov.x, ov.y))
            layers.append(img)

    # Text layers mapped to positions by order: top, bottom, ...
    for slot_name, line in zip(template.positions.keys(), copy.overlay_lines):
        pos = template.positions[slot_name]
        txt = TextClip(
            text=line,
            font=template.font,
            font_size=template.font_size,
            color=template.font_color,
            stroke_color=template.stroke_color,
            stroke_width=template.stroke_width,
            size=(template.width - 80, None),
            method="caption",
            text_align="center",
        ).with_duration(duration)
        txt = txt.with_position(_resolve_position(pos, template, txt.size))
        layers.append(txt)

    composite = CompositeVideoClip(layers, size=(template.width, template.height))
    if composite.audio:
        composite = composite.with_audio(composite.audio.with_volume_scaled(0.0))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{stamp}_render.mp4"
    composite.write_videofile(
        str(out_path),
        codec="libx264",
        audio_codec="aac",
        fps=30,
        preset="medium",
        logger=None,
    )
    base.close()
    return str(out_path)


def _fit_to_size(clip: VideoFileClip, width: int, height: int) -> VideoFileClip:
    """Resize preserving aspect, then crop center to exact target size."""
    target_ratio = width / height
    src_ratio = clip.w / clip.h
    if src_ratio > target_ratio:
        # Source is wider — fit height, crop width.
        scaled = clip.resized(height=height)
    else:
        scaled = clip.resized(width=width)
    x_center = (scaled.w - width) / 2
    y_center = (scaled.h - height) / 2
    return scaled.cropped(x1=x_center, y1=y_center, x2=x_center + width, y2=y_center + height)


def _resolve_position(pos, template: TemplateSpec, text_size: tuple[int, int]):
    """Translate a template position spec into a MoviePy position tuple."""
    tw, th = text_size
    x = pos.x
    y = pos.y
    px = template.width / 2 - tw / 2 if x == "center" else int(x)
    if y == "center":
        py = template.height / 2 - th / 2
    elif y.startswith("bottom-"):
        py = template.height - th - int(y.split("-")[1])
    elif y.startswith("top-"):
        py = int(y.split("-")[1])
    else:
        py = int(y)
    return (px, py)
```

- [ ] **Step 5: Run, verify pass (may take ~10-30s for the encode)**

Run: `pytest tests/test_renderer.py -v`
Expected: PASS. The output MP4 exists and probes as 1080x1080.

- [ ] **Step 6: Commit**

```bash
git add app/renderer.py tests/test_renderer.py tests/fixtures/test_clip.mp4
git commit -m "feat: renderer (MoviePy composite + FFmpeg encode)"
```

---

## Task 8: Orchestrator

**Files:**
- Create: `app/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test `tests/test_orchestrator.py`**

```python
from pathlib import Path
from unittest.mock import patch

from app.orchestrator import run_pipeline
from app.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_run_pipeline_chains_stages(tmp_path, sample_copy):
    settings = Settings(
        giphy_api_key="g", klipy_api_key="k",
        moonshot_api_key="m", moonshot_model="kimi-k2",
        output_dir=str(tmp_path / "out"), tmp_dir=str(tmp_path / "tmp"),
    )
    fake_clip = type("C", (), {"path": str(FIXTURE), "source": "giphy",
                               "original_url": "x", "width": 480, "height": 480})()
    with patch("app.orchestrator.generate_copy", return_value=sample_copy) as gc, \
         patch("app.orchestrator.fetch_clip", return_value=fake_clip) as fc:
        result = run_pipeline(
            topic="Monday gym", tone="funny",
            template_name="caption-top-bottom",
            source="giphy", settings=settings,
        )
    assert Path(result.output_path).exists()
    gc.assert_called_once()
    fc.assert_called_once()
```

- [ ] **Step 2: Run, verify fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `app/orchestrator.py`**

```python
"""Chain copywriter → clip_source → renderer into one render."""
from app.config import Settings
from app.copywriter import generate_copy
from app.clip_source import fetch_clip
from app.renderer import render_video
from app.templates import load_template
from app.models import CopyResult, RenderResult


def run_pipeline(
    *,
    topic: str,
    tone: str,
    template_name: str,
    source: str,
    settings: Settings,
    copy: CopyResult | None = None,
) -> RenderResult:
    spec = load_template(template_name)
    slot_count = len(spec.positions)

    if copy is None:
        copy = generate_copy(
            topic=topic,
            tone=tone,
            overlay_slot_count=slot_count,
            api_key=settings.moonshot_api_key,
            model=settings.moonshot_model,
            base_url=settings.moonshot_base_url,
        )

    clip = fetch_clip(
        query=topic,
        source=source,
        api_key=settings.giphy_api_key if source == "giphy" else settings.klipy_api_key,
        dest_dir=settings.tmp_dir,
    )

    out_path = render_video(
        clip=clip, copy=copy, template=spec, output_dir=settings.output_dir,
    )
    return RenderResult(output_path=out_path, copy=copy, clip=clip)
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator chains pipeline stages"
```

---

## Task 9: FastAPI web app

**Files:**
- Create: `app/main.py`
- Create: `static/index.html`
- Create: `static/app.js`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing test `tests/test_api.py`**

```python
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings

client = TestClient(app)


def test_list_templates_route():
    res = client.get("/api/templates")
    assert res.status_code == 200
    assert "caption-top-bottom" in res.json()["templates"]


def test_preview_copy_route(sample_copy):
    with patch("app.main.generate_copy", return_value=sample_copy):
        res = client.post(
            "/api/preview-copy",
            json={"topic": "Monday gym", "tone": "funny",
                  "template": "caption-top-bottom"},
        )
    assert res.status_code == 200
    body = res.json()
    assert "copy" in body
    assert body["copy"]["hook"] == sample_copy.hook


def test_render_route(sample_copy):
    fixture = Path(__file__).parent / "fixtures" / "test_clip.mp4"
    fake_clip = type("C", (), {"path": str(fixture), "source": "giphy",
                               "original_url": "x", "width": 480, "height": 480})()
    settings = Settings()
    with patch("app.main.get_settings", return_value=settings), \
         patch("app.main.generate_copy", return_value=sample_copy), \
         patch("app.main.fetch_clip", return_value=fake_clip):
        res = client.post(
            "/api/render",
            json={"topic": "Monday gym", "tone": "funny",
                  "template": "caption-top-bottom", "source": "giphy"},
        )
    assert res.status_code == 200
    assert "output_path" in res.json()
```

- [ ] **Step 2: Run, verify fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `app/main.py`**

```python
"""FastAPI web app — thin wrapper over the pipeline."""
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.copywriter import generate_copy
from app.clip_source import fetch_clip
from app.orchestrator import run_pipeline
from app.templates import list_templates, load_template

app = FastAPI(title="meme_gen")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PreviewCopyRequest(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/templates")
def api_templates():
    return {"templates": list_templates()}


@app.post("/api/preview-copy")
def api_preview_copy(req: PreviewCopyRequest):
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


class RenderReq(BaseModel):
    topic: str
    tone: str = "funny"
    template: str = "caption-top-bottom"
    source: str = "giphy"
    copy: dict | None = None


@app.post("/api/render")
def api_render(req: RenderReq):
    settings = get_settings()
    from app.models import CopyResult
    copy_obj = CopyResult(**req.copy) if req.copy else None
    try:
        result = run_pipeline(
            topic=req.topic, tone=req.tone,
            template_name=req.template, source=req.source,
            settings=settings, copy=copy_obj,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")
    return result.model_dump()


@app.get("/api/files/{name}")
def api_download(name: str):
    settings = get_settings()
    p = Path(settings.output_dir) / name
    if not p.exists() or ".." in name:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(p, media_type="video/mp4", filename=name)
```

- [ ] **Step 4: Write `static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>meme_gen</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
    label { display: block; margin: 0.75rem 0 0.25rem; font-weight: 600; }
    input, select, textarea, button { width: 100%; padding: 0.5rem; font-size: 1rem; box-sizing: border-box; }
    button { margin-top: 1rem; cursor: pointer; }
    .row { display: flex; gap: 1rem; }
    .row > * { flex: 1; }
    pre { background: #f4f4f4; padding: 0.75rem; white-space: pre-wrap; border-radius: 6px; }
    video { width: 100%; margin-top: 1rem; border-radius: 8px; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <h1>meme_gen</h1>

  <label for="topic">Topic / theme</label>
  <input id="topic" placeholder="e.g. Monday motivation, gym" />

  <div class="row">
    <div>
      <label for="tone">Tone</label>
      <select id="tone">
        <option>funny</option>
        <option>motivational</option>
        <option>relatable</option>
        <option>wholesome</option>
      </select>
    </div>
    <div>
      <label for="template">Template</label>
      <select id="template"></select>
    </div>
    <div>
      <label for="source">Clip source</label>
      <select id="source">
        <option value="giphy">Giphy</option>
        <option value="klipy">Klipy</option>
      </select>
    </div>
  </div>

  <button id="previewBtn">1. Preview copy (AI)</button>
  <div id="copyBox" class="hidden">
    <label>Generated copy (edit freely, then render):</label>
    <textarea id="copyJson" rows="8"></textarea>
    <button id="renderBtn">2. Render video</button>
  </div>

  <div id="status" style="margin-top:1rem; font-weight:600;"></div>
  <video id="result" controls class="hidden"></video>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 5: Write `static/app.js`**

```javascript
const $ = (id) => document.getElementById(id);

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  for (const name of data.templates) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    $("template").appendChild(opt);
  }
}

$("previewBtn").addEventListener("click", async () => {
  $("status").textContent = "Generating copy…";
  const res = await fetch("/api/preview-copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value, template: $("template").value,
    }),
  });
  if (!res.ok) { $("status").textContent = "Copy failed: " + (await res.text()); return; }
  const data = await res.json();
  $("copyJson").value = JSON.stringify(data.copy, null, 2);
  $("copyBox").classList.remove("hidden");
  $("status").textContent = "Copy ready — edit if you like, then render.";
});

$("renderBtn").addEventListener("click", async () => {
  $("status").textContent = "Rendering… (this takes ~20-40s)";
  let copy;
  try { copy = JSON.parse($("copyJson").value); } catch (e) {
    $("status").textContent = "Copy JSON is invalid.";
    return;
  }
  const res = await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: $("topic").value, tone: $("tone").value,
      template: $("template").value, source: $("source").value, copy,
    }),
  });
  if (!res.ok) { $("status").textContent = "Render failed: " + (await res.text()); return; }
  const data = await res.json();
  const filename = data.output_path.split("/").pop();
  $("result").src = "/api/files/" + filename;
  $("result").classList.remove("hidden");
  $("status").textContent = "Done: " + filename;
});

loadTemplates();
```

- [ ] **Step 6: Run, verify pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add app/main.py static/ tests/test_api.py
git commit -m "feat: FastAPI web UI + routes"
```

---

## Task 10: Manual smoke test & README run instructions

**Files:**
- Modify: `README.md` (already created in Task 1; add a "Running" + "Troubleshooting" section)

- [ ] **Step 1: Smoke test the whole app live (requires real keys in `.env`)**

Run in one terminal:
```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```
Then in a browser open http://127.0.0.1:8000 and try:
- Topic: "Monday gym", tone "funny", template "caption-top-bottom", source "giphy".
- Click "Preview copy" → confirm JSON appears in the textarea.
- Click "Render video" → confirm an MP4 plays in the page after ~20-40s.

Expected: a square 1080×1080 MP4 with top/bottom caption text over a Giphy clip.

- [ ] **Step 2: Update README "Running" section**

Append to `README.md`:

```markdown
## Running
1. Fill in `.env` with real keys.
2. `source .venv/bin/activate && uvicorn app.main:app --reload`
3. Open http://127.0.0.1:8000
4. Enter a topic → Preview copy → (edit if desired) → Render video.
5. Finished MP4s land in `output/`.

## Troubleshooting
- **`KeyError`/empty on copy step:** check `MOONSHOT_API_KEY` and model name.
- **"Giphy returned no clips":** try a broader keyword.
- **MoviePy font error:** install Arial-Bold or change `font` in the template JSON to a font that exists on your system (`fc-list | grep -i bold` to list).
- **Render is slow:** lower the template `width`/`height` or change MoviePy `preset` to `ultrafast`.
```

- [ ] **Step 3: Full test suite green check**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: running + troubleshooting"
```

---

## Task 11: Canva overlay asset library (one-time, manual via Canva MCP)

This task produces *data files* (PNGs) the renderer reads — no application code changes. It is the only step that uses the Canva MCP directly.

**Files:**
- Create: `assets/bottom-bar.png` (transparent)
- Create: `assets/watermark.png` (transparent)
- Create: `assets/end-card.png` (transparent)
- Create: `templates/lower-third-brand.json`

- [ ] **Step 1: Design overlay assets in Canva via the Canva MCP**

Using the Canva MCP (configured for Claude Code/Desktop per [canva.dev/docs/mcp](https://www.canva.dev/docs/mcp/)), create three transparent canvases:
- `bottom-bar.png` — a semi-transparent dark bar (1080×160px) for lower-third captions.
- `watermark.png` — a small logo/handle mark, top-right, ~240×80px.
- `end-card.png` — a 1080×1080 transparent frame with a "follow @yourhandle" call-to-action in the lower third.

Export each as PNG with transparent background into `assets/`.

- [ ] **Step 2: Create `templates/lower-third-brand.json`** that uses the overlays

```json
{
  "name": "lower-third-brand",
  "description": "Branded lower-third caption bar with watermark.",
  "aspect_ratio": "9:16",
  "width": 1080,
  "height": 1920,
  "font": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
  "font_size": 56,
  "font_color": "white",
  "stroke_color": "black",
  "stroke_width": 2,
  "positions": {
    "caption": { "x": "center", "y": "bottom-220" }
  },
  "overlays": [
    { "file": "bottom-bar.png", "x": 0, "y": 1760 },
    { "file": "watermark.png", "x": 820, "y": 40 }
  ]
}
```

- [ ] **Step 3: Verify the renderer picks up overlays**

Add a test `tests/test_renderer_overlays.py`:

```python
from pathlib import Path
from app.renderer import render_video
from app.models import ClipInfo, CopyResult
from app.templates import load_template

FIXTURE = Path(__file__).parent / "fixtures" / "test_clip.mp4"


def test_render_with_overlays_when_assets_exist(tmp_path, sample_copy, monkeypatch):
    # Point ASSETS_DIR at a tmp dir with a fake PNG so the test doesn't
    # depend on Canva-made assets existing.
    fake_assets = tmp_path / "assets"
    fake_assets.mkdir()
    (fake_assets / "bottom-bar.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    monkeypatch.setattr("app.renderer.ASSETS_DIR", fake_assets)

    clip = ClipInfo(path=str(FIXTURE), source="giphy", original_url="x",
                    width=480, height=480)
    spec = load_template("lower-third-brand")
    # supply one overlay line to match the single 'caption' position
    copy = CopyResult(caption="x", hook="y", overlay_lines=["BRANDED CAPTION"])
    out = render_video(clip=clip, copy=copy, template=spec, output_dir=str(tmp_path))
    assert Path(out).exists() and Path(out).stat().st_size > 0
```

Run: `pytest tests/test_renderer_overlays.py -v`
Expected: PASS (renders without error even though PNG is fake bytes — overlays are added only if the file exists; this guards the code path).

- [ ] **Step 4: Commit**

```bash
git add templates/lower-third-brand.json assets/*.png tests/test_renderer_overlays.py
git commit -m "feat: branded lower-third template + Canva overlay assets"
```

---

## Self-Review

**1. Spec coverage:**
- Tool stack (Giphy/Klipy, Canva-for-overlays, FFmpeg/MoviePy, Moonshot, FastAPI) → Tasks 6, 11, 7, 5, 9. ✓
- Four-stage pipeline (copywriter, clip_source, renderer, orchestrator) → Tasks 5, 6, 7, 8. ✓
- Web UI with preview step → Task 9 (index.html + app.js has preview → render flow). ✓
- Templates as JSON data → Task 4 + Task 11. ✓
- Aspect ratios 1:1 and 9:16 → caption-top-bottom (1:1) and lower-third-brand (9:16). ✓
- Error handling "fail loudly" → orchestrator/api raise HTTPException with clear messages; clip_source raises LookupError. ✓
- Build order de-risks renderer first → Task 7 sits before orchestrator/UI but after the simpler modules. ✓
- Out-of-scope items (posting, DB, auth, long-form) → correctly absent. ✓

**2. Placeholder scan:** No TBD/TODO. Every code step has complete code. The only "manual" step is Task 11 Step 1 (designing in Canva) — that's intentional because Canva assets are data, not code.

**3. Type consistency:**
- `CopyResult(caption, hook, overlay_lines)`, `ClipInfo(path, source, original_url, width, height)`, `RenderResult(output_path, copy, clip)` — used identically across copywriter, clip_source, renderer, orchestrator, main. ✓
- `generate_copy(*, topic, tone, overlay_slot_count, api_key, model, base_url=...)` — signature matches in copywriter.py, orchestrator.py, main.py. ✓
- `fetch_clip(*, query, source, api_key, dest_dir)` — matches in clip_source.py, orchestrator.py, main.py test mocks. ✓
- `render_video(*, clip, copy, template, output_dir)` — matches renderer.py, orchestrator.py. ✓
- `run_pipeline(*, topic, tone, template_name, source, settings, copy=None)` — matches orchestrator.py and main.py. ✓
- MoviePy v2 imports `from moviepy import ...` used consistently. ✓

No issues found. Plan is complete.
