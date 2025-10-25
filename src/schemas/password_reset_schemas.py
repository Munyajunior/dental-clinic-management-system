# src/schemas/password_reset_schemas.py
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


class PasswordResetRequest(BaseModel):
    """Password reset request schema"""

    email: EmailStr


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


class PasswordResetResponse(BaseModel):
    """Password reset response schema"""

    success: bool
    message: str
