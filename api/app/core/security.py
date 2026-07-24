"""Single-tenant demo auth: shared API key for dashboard calls."""

from fastapi import Header, HTTPException

from app.config import settings


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail={"detail": "Invalid API key", "code": "unauthorized"})
