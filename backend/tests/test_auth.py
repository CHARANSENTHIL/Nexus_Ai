import pytest
from fastapi import HTTPException
from app.auth.jwt import create_access_token, decode_access_token
from app.auth.whitelist import is_user_whitelisted, verify_telegram_user

def test_jwt_create_and_decode():
    data = {"sub": "12345", "role": "admin"}
    token = create_access_token(data)
    decoded = decode_access_token(token)
    assert decoded["sub"] == "12345"
    assert decoded["role"] == "admin"
    assert "exp" in decoded

def test_jwt_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("invalid.token.signature")
    assert exc_info.value.status_code == 401

def test_telegram_whitelist():
    from app.config import settings
    allowed_id = settings.TELEGRAM_ALLOWED_USER_IDS[0] if settings.TELEGRAM_ALLOWED_USER_IDS else 123456789
    assert is_user_whitelisted(allowed_id) is True
    assert is_user_whitelisted(999999999) is False
    
    assert verify_telegram_user(allowed_id) == allowed_id
    with pytest.raises(HTTPException) as exc_info:
        verify_telegram_user(999999999)
    assert exc_info.value.status_code == 403

