from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from .base_schemas import ResponseBase, BaseSchema


class TokenResponse(BaseSchema):
    """Token response schema"""

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    session_id: Optional[str] = None


class TokenRefreshResponse(TokenResponse):
    """Token refresh response schema"""

    pass


class RefreshTokenRequest(BaseSchema):
    """Refresh token request schema"""

    refresh_token: str


class LogoutRequest(BaseSchema):
    """Logout request schema"""

    refresh_token: Optional[str] = None


class LogoutResponse(ResponseBase):
    """Logout response schema"""

    sessions_revoked: Optional[int] = 0
    tokens_revoked: Optional[int] = 0


class SessionInfo(BaseSchema):
    """User session information"""

    session_id: UUID
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_time: datetime
    last_activity: datetime
    device_info: Optional[Dict[str, Any]] = None


class ActiveSessionsResponse(ResponseBase):
    """Active sessions response"""

    sessions: list[SessionInfo]
    total_sessions: int


class ForceLogoutRequest(BaseSchema):
    """Force logout request (admin only)"""

    user_id: UUID
    reason: Optional[str] = "admin_forced"


class SecurityEventCreate(BaseSchema):
    """Security event creation schema"""

    event_type: str
    severity: str  # low, medium, high, critical
    description: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class PasswordPolicyResponse(BaseSchema):
    """Password policy information"""

    min_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_numbers: bool
    require_special_chars: bool
    max_age_days: int
    examples: list[str]


class LoginSecurityResponse(BaseSchema):
    """Login security information"""

    max_login_attempts: int
    lockout_duration_minutes: int
    suspicious_activity_threshold: int
