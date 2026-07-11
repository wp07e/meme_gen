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
- OPENROUTER_API_KEY — https://openrouter.ai
- OPENROUTER_MODEL — any model slug from OpenRouter (e.g. `openai/gpt-4o-mini`, `openrouter/deepseek/deepseek-v4-flash:nitro`)

## Running
1. Fill in `.env` with real keys.
2. `source .venv/bin/activate && uvicorn app.main:app --reload`
3. Open http://127.0.0.1:8000
4. Enter a topic → Preview copy → (edit if desired) → Render video.
5. Finished MP4s land in `output/`.

## OpenRouter model notes
- Set `OPENROUTER_MODEL` to any model slug available on OpenRouter. Browse models
  at https://openrouter.ai/models.
- The app uses the OpenAI-compatible SDK pointed at OpenRouter's endpoint
  (`https://openrouter.ai/api/v1`).
- Default model (if unset): `openai/gpt-4o-mini`.

## Troubleshooting
- **"Giphy returned no clips":** try a broader/simpler keyword.
- **MoviePy font error:** the template `font` must be a **file path**, not a
  name. Default uses `/System/Library/Fonts/Supplemental/Arial Bold.ttf`
  (macOS). List bold fonts with `fc-list | grep -i bold`.
- **Render is slow:** lower the template `width`/`height` or change MoviePy
  `preset` to `ultrafast` in `app/renderer.py`.
