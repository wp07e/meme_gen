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
