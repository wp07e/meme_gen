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
