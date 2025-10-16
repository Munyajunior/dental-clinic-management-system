# src/schemas/auth_schemas.py
from pydantic import BaseModel
from typing import Optional


class TokenResponse(BaseModel):
    """Token response schema"""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema"""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request schema"""

    refresh_token: str


class LogoutResponse(BaseModel):
    """Logout response schema"""

    success: bool = True
    message: Optional[str] = None

    def dict(self, **kwargs):
        return super().model_dump(**kwargs)
