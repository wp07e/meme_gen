from app.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GIPHY_API_KEY", "g_key")
    monkeypatch.setenv("KLIPY_API_KEY", "k_key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    settings = Settings()
    assert settings.giphy_api_key == "g_key"
    assert settings.klipy_api_key == "k_key"
    assert settings.openrouter_api_key == "or_key"
    assert settings.openrouter_model == "openai/gpt-4o-mini"
    assert settings.host == "127.0.0.1"  # default
    assert settings.port == 8000
