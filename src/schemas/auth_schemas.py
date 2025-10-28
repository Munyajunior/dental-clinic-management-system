# src/schemas/auth_schemas.py
from schemas.base_schemas import ResponseBase, BaseSchema
from pydantic import BaseModel, EmailStr
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


class LogoutResponse(ResponseBase):
    """Logout response schema"""

    pass
