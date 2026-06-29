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

## Running
1. Fill in `.env` with real keys.
2. `source .venv/bin/activate && uvicorn app.main:app --reload`
3. Open http://127.0.0.1:8000
4. Enter a topic → Preview copy → (edit if desired) → Render video.
5. Finished MP4s land in `output/`.

## Moonshot model notes
- Set `MOONSHOT_MODEL` to a **general** model your key can access. The general
  models are `kimi-k2.5` / `kimi-k2.6` (`kimi-k2.7-code*` are coding-only and
  will 404). Check your available models with:
  `.venv/bin/python -c "from openai import OpenAI; from app.config import Settings; s=Settings(); [print(m.id) for m in OpenAI(api_key=s.moonshot_api_key, base_url=s.moonshot_base_url).models.list().data]"`
- These are **reasoning models**: the copywriter uses `temperature=1` (required),
  a high `max_tokens` budget, and falls back to `reasoning_content` if the
  visible `content` is empty.

## Troubleshooting
- **`404 ... Not found the model` on copy step:** `MOONSHOT_MODEL` in `.env` is
  not valid for your key. Pick from the list above.
- **`400 invalid temperature`:** only `temperature=1` is allowed for reasoning
  models — already handled by the copywriter.
- **"Giphy returned no clips":** try a broader/simpler keyword.
- **MoviePy font error:** the template `font` must be a **file path**, not a
  name. Default uses `/System/Library/Fonts/Supplemental/Arial Bold.ttf`
  (macOS). List bold fonts with `fc-list | grep -i bold`.
- **Render is slow:** lower the template `width`/`height` or change MoviePy
  `preset` to `ultrafast` in `app/renderer.py`.
