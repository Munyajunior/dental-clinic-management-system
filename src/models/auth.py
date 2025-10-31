# src/models/auth.py
import uuid
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone
from sqlalchemy.sql import func
from db.database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=True
    )

    # Token metadata
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Security fields
    ip_address = Column(String(45), nullable=True)  # IPv6 support
    user_agent = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")
    tenant = relationship("Tenant")
    session = relationship("UserSession", back_populates="refresh_tokens")

    def __repr__(self):
        return f"<RefreshToken {self.id} for user {self.user_id}>"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired"""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not expired and not revoked)"""
        return not self.is_expired and not self.is_revoked


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    token = Column(String(255), nullable=False, unique=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="password_reset_tokens")
    user = relationship("User", back_populates="password_reset_tokens")

    def __repr__(self):
        return f"<PasswordResetToken {self.token} for user {self.user_id}>"

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


class LoginAttempt(Base):
    """Track login attempts for security monitoring"""

    __tablename__ = "login_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    success = Column(Boolean, nullable=False)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="login_attempts")


class SecurityEvent(Base):
    """Audit trail for security events"""

    __tablename__ = "security_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    event_type = Column(String(100), nullable=False)  # login, password_change, etc.
    severity = Column(String(20), nullable=False)  # low, medium, high, critical
    description = Column(Text, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    tenant = relationship("Tenant")


class UserSession(Base):
    """User session management for comprehensive session tracking"""

    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # Session metadata
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    device_info = Column(JSON, nullable=True)  # Store device fingerprint

    # Session timing
    login_time = Column(DateTime(timezone=True), nullable=False)
    last_activity = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Session state
    is_active = Column(Boolean, default=True, nullable=False)
    logout_time = Column(DateTime(timezone=True), nullable=True)
    logout_reason = Column(
        String(100), nullable=True
    )  # user_logout, expired, security_policy

    # Security context
    refresh_token_id = Column(
        UUID(as_uuid=True), nullable=True
    )  # Associated refresh token

    # Relationships
    tenant = relationship("Tenant")
    user = relationship("User", back_populates="sessions")
    refresh_tokens = relationship("RefreshToken", back_populates="session")

    def __repr__(self):
        return f"<UserSession {self.id} for user {self.user_id}>"

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def duration(self) -> timedelta:
        """Get session duration"""
        end_time = self.logout_time or datetime.now(timezone.utc)
        return end_time - self.login_time
