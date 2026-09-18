from rift_api.config import Settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("RIFT_SERVICE_NAME", "test-rift-api")
    monkeypatch.setenv("RIFT_ENVIRONMENT", "test")
    monkeypatch.setenv("RIFT_DEBUG", "true")

    settings = Settings()

    assert settings.service_name == "test-rift-api"
    assert settings.environment == "test"
    assert settings.debug is True
