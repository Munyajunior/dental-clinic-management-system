from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    sub: UUID


class TokenData(BaseModel):
    email: Optional[EmailStr] = None
