"""Configuration loaded from environment / .env."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class Settings:
    # Read at instantiation (not import time) so tests can monkeypatch env.
    giphy_api_key: str = field(default_factory=lambda: _env("GIPHY_API_KEY"))
    klipy_api_key: str = field(default_factory=lambda: _env("KLIPY_API_KEY"))
    moonshot_api_key: str = field(default_factory=lambda: _env("MOONSHOT_API_KEY"))
    moonshot_model: str = field(default_factory=lambda: _env("MOONSHOT_MODEL", "kimi-k2"))
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    output_dir: str = "output"
    tmp_dir: str = "tmp"


def get_settings() -> Settings:
    return Settings()
