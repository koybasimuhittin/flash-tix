from flashtix_common.config import BaseServiceSettings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "booking")
    monkeypatch.setenv("SLOW_REQUEST_MS", "250")
    settings = BaseServiceSettings()
    assert settings.service_name == "booking"
    assert settings.slow_request_ms == 250
    assert (settings.jwt_issuer, settings.jwt_audience) == ("flashtix-auth", "flashtix")
