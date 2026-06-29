# meme_gen — Automated Meme Video Generator (Design Spec)

**Date:** 2026-06-29
**Status:** Draft (awaiting user review)

## 1. Purpose
Generate short, branded meme videos from a topic/theme, fully automated
except for an optional copy-preview step. Output is an MP4 ready to post
to Facebook or Instagram (manual posting in v1; auto-posting deferred).

## 2. Core Workflow (agreed)
"Clip + my text/brand overlay" combined with "template fill-in":
source a trending meme clip, drop it into a layout template, overlay
Canva-designed brand assets and AI-generated text, export.

## 3. Tool Stack (corrected from user's original assumptions)
- **Giphy + Klipy** — meme/GIF clip sourcing (free API keys).
- **Canva MCP (official)** — design reusable transparent-PNG overlay
  assets (panels, bars, end-cards, watermark) ONE TIME. Canva is NOT
  used as the video canvas; it produces static compositing assets.
- **FFmpeg + MoviePy (Python)** — the actual video compositor/encoder.
  This replaces the user's requested "CapCut MCP," which has no
  official automatable API.
- **Moonshot Kimi (latest)** — copywriting via OpenAI-compatible API.
- **FastAPI + Jinja templates** — local web UI.

**Why not CapCut:** No official public API for editing automation;
community wrappers (CapCutAPI, VectCutAPI) are unofficial and fragile.
FFmpeg/MoviePy is the reliable, free, scriptable alternative.

## 4. Architecture
```
Local Web UI (FastAPI, localhost)
        |  HTTP
        v
Pipeline Core (Python)
  copywriter.py    — Moonshot Kimi -> {caption, hook, overlay_lines[]}
  clip_source.py   — Giphy/Klipy   -> downloaded clip path
  renderer.py      — MoviePy/FFmpeg-> composited MP4
  orchestrator.py  — chains the three stages
Templates = JSON layout specs (data, not code).
Assets   = Canva-exported transparent PNG overlays.
```

Component boundaries (each isolated, independently testable):
- `copywriter.py` — pure function over Moonshot API; no IO.
- `clip_source.py` — provider-swappable (Giphy/Klipy/Tenor).
- `renderer.py` — deterministic given inputs; writes only to output/.
- `templates/` — JSON; new format = new file, no code change.
- `orchestrator.py` — only place that knows the full flow.
- Web UI — thin, no business logic.

No database, no auth in v1 (local-only, file-based state).

## 5. Data Flow (one render)
1. User enters topic + picks template in web UI.
2. POST /render {topic, tone, template, source}.
3. copywriter -> Moonshot returns caption/hook/overlay lines.
4. UI optionally previews copy for user edit (preview step).
5. clip_source -> queries Giphy/Klipy, downloads best clip to tmp/.
6. renderer -> loads template JSON, composites clip + Canva PNG +
   rendered text, encodes H.264 MP4 at template's aspect ratio
   (1:1 feed or 9:16 reels/stories).
7. Output -> output/<timestamp>_<topic>.mp4; UI shows in <video> + download link.

Error handling: each stage fails loudly with clear messages; no silent
fallbacks. Missing API key -> friendly setup screen, not a stack trace.

## 6. Project Structure
```
meme_gen/
├── README.md
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py            # FastAPI app + routes
│   ├── orchestrator.py
│   ├── copywriter.py
│   ├── clip_source.py
│   ├── renderer.py
│   └── templates.py
├── templates/             # JSON layout specs
├── assets/                # Canva PNG overlays + README
├── static/                # minimal frontend HTML/JS
└── tests/
```

## 7. Build Order (each milestone independently usable)
1. renderer.py + one template + hard-coded clip — de-risk hardest part.
2. clip_source.py — wire Giphy/Klipy.
3. copywriter.py — wire Moonshot.
4. orchestrator.py — chain stages.
5. Web UI — preview + render flow.
6. Canva asset library — design overlays via MCP (anytime; assets are files).

## 8. Out of Scope (v1)
- Automatic posting to FB/IG (Meta Graph API, app review, tokens).
- Database / history / scheduling.
- Auth (local-only).
- Original long-form video editing.

## 9. Open Items / Assumptions
- Aspect ratios: 1:1 and 9:16 supported from day 1 (FB/IG native).
- Renderer crops/pads sourced clips to template ratio.
- Moonshot model id: use latest available at build time.
- API keys supplied by user via .env (GIPHY_KEY, KLIPY_KEY,
  MOONSHOT_KEY, plus Canva MCP config).
