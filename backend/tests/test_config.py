import pytest
from app.config import Settings, settings

def test_default_settings():
    assert settings.PROJECT_NAME == "Nexus AI"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.ALGORITHM == "HS256"

def test_telegram_ids_parsing():
    s = Settings(TELEGRAM_ALLOWED_USER_IDS="123,456,789")
    assert s.TELEGRAM_ALLOWED_USER_IDS == [123, 456, 789]
    
    s_empty = Settings(TELEGRAM_ALLOWED_USER_IDS="")
    assert s_empty.TELEGRAM_ALLOWED_USER_IDS == []
