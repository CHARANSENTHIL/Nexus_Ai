from fastapi import HTTPException, status
from app.config import settings

def is_user_whitelisted(user_id: int) -> bool:
    allowed_ids = settings.TELEGRAM_ALLOWED_USER_IDS
    if isinstance(allowed_ids, list):
        return user_id in allowed_ids
    return False

def verify_telegram_user(user_id: int) -> int:
    if not is_user_whitelisted(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User ID {user_id} is not whitelisted."
        )
    return user_id
