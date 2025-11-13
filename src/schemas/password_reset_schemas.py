# src/schemas/password_reset_schemas.py
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from .base_schemas import BaseSchema, ResponseBase
from schemas.user_schemas import UserPublic
from uuid import UUID


class PasswordResetRequest(BaseModel):
    """Password reset request schema"""

    user_id: UUID


class PasswordResetVerify(BaseModel):
    """Password reset token verification schema"""

    token: str


class PasswordResetComplete(BaseModel):
    """Password reset completion schema"""

    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class PasswordResetResponse(ResponseBase):
    """Password reset response schema"""

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: Optional[UserPublic] = None


class EnforcedPasswordReset(BaseSchema):
    email: EmailStr
    new_password: str
    tenant_slug: str


class ChangePasswordRequest(BaseModel):
    """User password change schema"""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class AdminForcePasswordReset(BaseModel):
    """Schema for admin forcing password reset"""

    user_id: str
    reason: Optional[str] = "Admin required password reset"
