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
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    openrouter_model: str = field(default_factory=lambda: _env("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    output_dir: str = field(default_factory=lambda: _env("OUTPUT_DIR", "output"))
    tmp_dir: str = field(default_factory=lambda: _env("TMP_DIR", "tmp"))
    uploads_dir: str = field(default_factory=lambda: _env("UPLOADS_DIR", "uploads"))
    # --- Auth (login + admin). Set SECRET_KEY/ADMIN_* in .env for a real deploy. ---
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-only-insecure-secret-change-me"))
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", "testadmin"))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", "testpass123"))
    # --- Analytics. Set GTM_CONTAINER_ID in .env; leave blank to disable GTM. ---
    gtm_container_id: str = field(default_factory=lambda: _env("GTM_CONTAINER_ID", ""))


# Default secret used when SECRET_KEY is not configured. Compared against at
# startup to warn if the app is running with the insecure shipped default.
DEFAULT_SECRET_KEY = "dev-only-insecure-secret-change-me"


def get_settings() -> Settings:
    return Settings()
