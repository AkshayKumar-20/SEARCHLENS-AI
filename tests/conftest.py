import pytest

from backend.app.config import settings


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    """Keep the suite offline even if a developer's .env holds real API keys."""
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "pagespeed_api_key", "")
