# src/services/auth_service.py
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func, update
from fastapi import HTTPException, status, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
import httpx
from db.database import get_db
from db.database import AsyncSessionLocal
from core.config import settings
from models.user import StaffRole, GenderEnum
from models.user import User
from models.tenant import Tenant, TenantPaymentStatus, TenantTier, BillingCycle
from models.auth import RefreshToken, LoginAttempt, UserSession
from schemas.user_schemas import UserLogin, UserCreate, UserWorkSchedule
from services.email_service import email_service
from services.email_integration_service import email_integration_service
from services.usage_service import UsageService
from services.payment_service import PaymentService
from utils.logger import setup_logger
from .base_service import BaseService
import secrets
import string
import hashlib
import asyncio

logger = setup_logger("AUTH_SERVICE")

security = HTTPBearer()
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# Helper function for consistent UTC datetime
def get_utc_now() -> datetime:
    """Get current UTC datetime with timezone awareness"""
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is UTC timezone aware"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PasswordPolicyService:
    """Enterprise password policy enforcement"""

    def __init__(self):
        self.min_length = 8
        self.require_uppercase = True
        self.require_lowercase = True
        self.require_numbers = True
        self.require_special_chars = False  # Make special chars optional
        self.max_age_days = 180  # 6 months instead of 90 days (password expiration)
        self.history_size = 3  # Remember last 3 passwords

    def validate_password_strength(self, password: str) -> Tuple[bool, List[str]]:
        """Validate password against enterprise policy"""
        errors = []

        if len(password) < self.min_length:
            errors.append(
                f"Password must be at least {self.min_length} characters long"
            )

        if self.require_uppercase and not any(c.isupper() for c in password):
            errors.append("Password must contain at least one uppercase letter")

        if self.require_lowercase and not any(c.islower() for c in password):
            errors.append("Password must contain at least one lowercase letter")

        if self.require_numbers and not any(c.isdigit() for c in password):
            errors.append("Password must contain at least one number")

        if self.require_special_chars and not any(
            c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password
        ):
            errors.append("Password must contain at least one special character")

        # Check against common passwords
        if self.is_password_compromised(password):
            errors.append(
                "This password is too common. Please choose a more secure password."
            )

        # Check entropy
        if self.calculate_password_entropy(password) < 40:  # Reduced from 60 bits
            errors.append(
                "Password is not complex enough. Please use a more varied combination of characters."
            )

        return len(errors) == 0, errors

    def is_password_compromised(self, password: str) -> bool:
        """Enhanced compromised password check using Pwned Passwords API"""
        try:
            # Calculate SHA-1 hash of password
            password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
            prefix, suffix = password_hash[:5], password_hash[5:]

            # Check against Have I Been Pwned API
            url = f"https://api.pwnedpasswords.com/range/{prefix}"
            response = httpx.get(url, timeout=5.0)

            if response.status_code == 200:
                hashes = response.text.split("\n")
                for hash_line in hashes:
                    if hash_line.startswith(suffix):
                        count = int(hash_line.split(":")[1])
                        return (
                            count > 10
                        )  # Consider compromised if found more than 10 times

        except Exception as e:
            logger.warning(f"Could not check password against Pwned Passwords API: {e}")
            # Fallback to basic check
            return self._basic_compromised_check(password)

        return False

    def _basic_compromised_check(self, password: str) -> bool:
        """Basic compromised password check"""
        common_passwords = {
            "password",
            "123456",
            "password123",
            "admin",
            "qwerty",
            "letmein",
            "welcome",
            "monkey",
            "dragon",
            "master",
            "12345678",
            "123456789",
            "1234567890",
            "abc123",
            "password1",
            "123123",
            "000000",
            "iloveyou",
            "sunshine",
            "princess",
            "1234",
            "12345",
            "1234567",
            "111111",
            "photoshop",
            "123",
            "123abc",
            "aaa",
            "abc",
            "access",
            "adobe",
            "ashley",
            "azerty",
            "bailey",
            "baseball",
            "batman",
            "charlie",
            "donald",
            "dragon",
            "flower",
            "football",
            "freedom",
            "hello",
            "hottie",
            "illustrator",
            "jesus",
            "letmein",
            "login",
            "lovely",
            "michael",
            "mustang",
            "ninja",
            "passw0rd",
            "password",
            "password1",
            "photoshop",
            "princess",
            "qazwsx",
            "qqww1122",
            "shadow",
            "solo",
            "starwars",
            "sunshine",
            "superman",
            "trustno1",
            "welcome",
            "whatever",
            "zaq1zaq1",
        }

        # Also check simple variations
        simple_variations = (
            {f"{base}123" for base in common_passwords}
            | {f"{base}!" for base in common_passwords}
            | {f"{base}1" for base in common_passwords}
        )

        all_compromised = common_passwords | simple_variations

        return password.lower() in all_compromised

    def calculate_password_entropy(self, password: str) -> float:
        """Calculate password entropy in bits"""
        import math

        # Character pool size
        pool_size = 0
        if any(c.islower() for c in password):
            pool_size += 26
        if any(c.isupper() for c in password):
            pool_size += 26
        if any(c.isdigit() for c in password):
            pool_size += 10
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            pool_size += 22  # Extended special characters

        if pool_size == 0:
            return 0

        entropy = len(password) * math.log2(pool_size)
        return entropy

    def is_password_expired(self, user: User) -> bool:
        """Check if user's password has expired - FIXED VERSION"""
        try:
            # Use settings instead of updated_at to avoid database access
            user_settings = getattr(user, "settings", {}) or {}
            password_changed_at = user_settings.get("password_changed_at")

            if password_changed_at:
                # Parse the timestamp from settings
                if isinstance(password_changed_at, str):
                    changed_dt = datetime.fromisoformat(
                        password_changed_at.replace("Z", "+00:00")
                    )
                else:
                    changed_dt = password_changed_at

                password_age = get_utc_now() - changed_dt
                return password_age.days > self.max_age_days

            # Fallback to updated_at if no password_changed_at in settings
            # But access it safely to avoid triggering database reload
            if hasattr(user, "updated_at") and user.updated_at is not None:
                password_age = get_utc_now() - user.updated_at
                return password_age.days > self.max_age_days

            return False

        except Exception as e:
            logger.warning(
                f"Error checking password expiration for user {getattr(user, 'email', 'unknown')}: {e}"
            )
            return False  # Don't block login on error

    def get_password_guidelines(self) -> Dict[str, Any]:
        """Get user-friendly password guidelines"""
        return {
            "min_length": self.min_length,
            "requirements": [
                "At least one uppercase letter",
                "At least one lowercase letter",
                "At least one number",
                "Special characters are optional but recommended",
            ],
            "recommendations": [
                "Use a mix of different character types",
                "Avoid common words and personal information",
                "Consider using a passphrase for better memorability",
                "Don't reuse passwords from other services",
            ],
            "examples": [
                "Summer2024!Clinic",
                "GreenTea@September",
                "OceanBreeze2024!",
                "MyDentalClinic2024",
            ],
        }


class TenantPaymentStatusService:
    """Enterprise tenant status and subscription management"""

    def __init__(self):
        self.usage_service = UsageService()
        self.payment_service = PaymentService()

    async def can_tenant_accept_logins(
        self, db: AsyncSession, tenant: Tenant
    ) -> Tuple[bool, str]:
        """
        Comprehensive tenant status checking for enterprise environment
        """
        current_time = get_utc_now()

        # Status-based checks
        payment_status_checks = {
            TenantPaymentStatus.CANCELLED: (
                False,
                "This clinic account has been cancelled. Please contact support.",
            ),
            TenantPaymentStatus.SUSPENDED: (
                False,
                "This clinic account has been suspended due to policy violation. Please contact support.",
            ),
            TenantPaymentStatus.PENDING: (True, "Account pending activation"),
        }

        if tenant.payment_status in payment_status_checks:
            return payment_status_checks[tenant.payment_status]

        # Trial account checks
        if tenant.payment_status == TenantPaymentStatus.TRIAL:
            # Check trial expiration
            if tenant.trial_ends_at and tenant.trial_ends_at < current_time:
                return (
                    False,
                    "Your trial period has ended. Please upgrade to continue using our services.",
                )

            # Check trial usage limits
            trial_limits_ok, limit_message = await self._check_trial_limits(db, tenant)
            if not trial_limits_ok:
                return False, limit_message

            return True, "Trial account active"

        # Active account checks
        elif tenant.payment_status == TenantPaymentStatus.ACTIVE:
            # Check subscription status for paid plans
            if tenant.tier != TenantTier.TRIAL:
                subscription_ok, sub_message = await self._check_subscription_status(
                    db, tenant
                )
                if not subscription_ok:
                    return False, sub_message

            # Check usage limits for all active accounts
            usage_ok, usage_message = await self._check_usage_limits(db, tenant)
            if not usage_ok:
                return False, usage_message

            return True, "Active account"

        # Grace period checks
        elif tenant.payment_status == TenantPaymentStatus.GRACE_PERIOD:
            if (
                tenant.grace_period_ends_at
                and tenant.grace_period_ends_at < current_time
            ):
                return (
                    False,
                    "Grace period has ended. Please update your payment method to continue.",
                )
            return True, "Account in grace period"

        return False, "Unknown account payment status. Please contact support."

    async def _check_trial_limits(
        self, db: AsyncSession, tenant: Tenant
    ) -> Tuple[bool, str]:
        """Check trial account limits with real usage data"""
        try:
            # Get current usage
            usage = await self.usage_service.get_tenant_usage(db, tenant.id)

            tier_features = self.get_tenant_tier_features(tenant.tier)

            # Check user limit
            if usage.get("active_users") >= tier_features["max_users"]:
                return (
                    False,
                    "Trial user limit reached. Please upgrade to add more users.",
                )

            # Check patient limit
            if usage.get("patient_count") >= tier_features["max_patients"]:
                return (
                    False,
                    "Trial patient limit reached. Please upgrade to add more patients.",
                )

            # Check storage limit
            if usage.get("storage_used_gb") >= tier_features["max_storage_gb"]:
                return (
                    False,
                    "Trial storage limit reached. Please upgrade for more storage.",
                )

            # Check API calls
            if usage.get("api_calls_this_month") >= tier_features.get(
                "max_api_calls", 1000
            ):
                return (
                    False,
                    "Trial API limit reached. Please upgrade for higher limits.",
                )

            return True, "Within trial limits"

        except Exception as e:
            logger.error(f"Error checking trial limits for tenant {tenant.id}: {e}")
            return (
                True,
                "Trial limits check temporarily unavailable",
            )  # Fail open for availability

    async def _check_subscription_status(
        self, db: AsyncSession, tenant: Tenant
    ) -> Tuple[bool, str]:
        """Check subscription status with payment provider integration"""
        try:
            # Check local subscription end date first
            if (
                tenant.subscription_ends_at
                and tenant.subscription_ends_at < datetime.utcnow()
            ):
                return False, "Your subscription has expired. Please renew to continue."

            # Integrate with payment provider for real-time status
            if tenant.stripe_subscription_id:
                subscription_status = (
                    await self.payment_service.get_subscription_status(
                        tenant.stripe_subscription_id
                    )
                )

                if subscription_status in ["canceled", "unpaid", "incomplete_expired"]:
                    return (
                        False,
                        "There's an issue with your subscription. Please update your payment method.",
                    )

                if subscription_status == "past_due":
                    # Check if we're in grace period
                    if (
                        not tenant.grace_period_ends_at
                        or tenant.grace_period_ends_at < get_utc_now()
                    ):
                        return (
                            False,
                            "Your payment is overdue. Please update your payment method.",
                        )

            return True, "Subscription active"

        except Exception as e:
            logger.error(
                f"Error checking subscription status for tenant {tenant.id}: {e}"
            )
            return True, "Subscription check temporarily unavailable"  # Fail open

    async def _check_usage_limits(
        self, db: AsyncSession, tenant: Tenant
    ) -> Tuple[bool, str]:
        """Check usage limits for active accounts"""
        try:
            usage = await self.usage_service.get_tenant_usage(db, tenant.id)
            tier_features = self.get_tenant_tier_features(tenant.tier)

            # Check if any limits are exceeded
            if usage.active_users >= tenant.max_users:
                return (
                    False,
                    "User limit reached. Please upgrade your plan to add more users.",
                )

            if usage.patient_count >= tenant.max_patients:
                return (
                    False,
                    "Patient limit reached. Please upgrade your plan to add more patients.",
                )

            if usage.storage_used_gb >= tenant.max_storage_gb:
                return (
                    False,
                    "Storage limit reached. Please upgrade your plan for more storage.",
                )

            if usage.api_calls_this_month >= tenant.max_api_calls_per_month:
                return (
                    False,
                    "API limit reached for this month. Please upgrade your plan.",
                )

            return True, "Within usage limits"

        except Exception as e:
            logger.error(f"Error checking usage limits for tenant {tenant.id}: {e}")
            return True, "Usage check temporarily unavailable"

    @staticmethod
    def get_tenant_tier_features(tier: TenantTier) -> Dict[str, Any]:
        """Get comprehensive features and limits for each tier"""
        base_features = {
            TenantTier.TRIAL: {
                "max_users": 5,
                "max_patients": 100,
                "max_storage_gb": 1,
                "max_api_calls_per_month": 1000,
                "features": [
                    "basic_appointments",
                    "patient_management",
                    "email_support",
                ],
                "support_level": "email_only",
                "trial_days": 30,
                "price": 0,
            },
            TenantTier.BASIC: {
                "max_users": 10,
                "max_patients": 1000,
                "max_storage_gb": 10,
                "max_api_calls_per_month": 10000,
                "features": [
                    "basic_appointments",
                    "patient_management",
                    "basic_reporting",
                    "email_reminders",
                    "business_hours_support",
                ],
                "support_level": "business_hours",
                "price": 99,
            },
            TenantTier.PROFESSIONAL: {
                "max_users": 25,
                "max_patients": 5000,
                "max_storage_gb": 50,
                "max_api_calls_per_month": 50000,
                "features": [
                    "advanced_appointments",
                    "patient_management",
                    "advanced_reporting",
                    "api_access",
                    "custom_forms",
                    "priority_support",
                    "sms_reminders",
                ],
                "support_level": "priority",
                "price": 299,
            },
            TenantTier.ENTERPRISE: {
                "max_users": 100,
                "max_patients": -1,  # Unlimited
                "max_storage_gb": 100,
                "max_api_calls_per_month": 200000,
                "features": [
                    "all_features",
                    "custom_integrations",
                    "dedicated_support",
                    "white_labeling",
                    "advanced_analytics",
                    "custom_workflows",
                    "sla_guarantee",
                ],
                "support_level": "dedicated",
                "price": 799,
            },
        }
        return base_features.get(tier, {})


class SecurityService:
    """Enterprise security features"""

    def __init__(self):
        self.max_login_attempts = 5
        self.lockout_duration = timedelta(minutes=30)
        self.suspicious_activity_threshold = 10

    async def check_login_security(
        self, db: AsyncSession, user: User, ip_address: str
    ) -> Tuple[bool, str]:
        """Comprehensive login security checks"""
        try:
            # Check if account is locked
            if user.settings and user.settings.get("account_locked_until"):
                lock_until = datetime.fromisoformat(
                    user.settings["account_locked_until"]
                )
                if lock_until > get_utc_now():
                    remaining = lock_until - get_utc_now()
                    return (
                        False,
                        f"Account temporarily locked. Try again in {remaining.seconds // 60} minutes.",
                    )

            # Check for suspicious activity
            if await self._has_suspicious_activity(db, user, ip_address):
                await self._lock_account(db, user, "Suspicious activity detected")
                return (
                    False,
                    "Suspicious activity detected. Account temporarily locked.",
                )

            return True, "Security checks passed"
        except Exception as e:
            logger.error(f"Security check error for user {user.email}: {str(e)}")
            # Fail open for availability - allow login if security checks fail
            return True, "Security checks temporarily unavailable"

    async def _has_suspicious_activity(
        self, db: AsyncSession, user: User, ip_address: str
    ) -> bool:
        """Detect suspicious login patterns"""
        # Check for multiple failed attempts from different IPs
        recent_failures = await db.execute(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.user_id == user.id,
                LoginAttempt.success == False,
                LoginAttempt.attempted_at > get_utc_now() - timedelta(hours=1),
            )
        )
        failure_count = recent_failures.scalar()

        return failure_count >= self.suspicious_activity_threshold

    async def record_login_attempt(
        self,
        db: AsyncSession,
        user: User,
        success: bool,
        ip_address: str,
        user_agent: str,
    ):
        """Record login attempt for security monitoring"""
        try:
            login_attempt = LoginAttempt(
                user_id=user.id,
                success=success,
                ip_address=ip_address,
                user_agent=user_agent,
                attempted_at=get_utc_now(),
            )
            db.add(login_attempt)

            if not success:
                await self._handle_failed_attempt(db, user)

            await db.commit()

            # Log security event for successful/failed attempts
            event_type = "login_success" if success else "login_failed"
            await self._log_security_event(db, user, event_type, ip_address, user_agent)

        except Exception as e:
            logger.error(f"Failed to record login attempt: {str(e)}")
            await db.rollback()

    async def _log_security_event(
        self,
        db: AsyncSession,
        user: User,
        event_type: str,
        ip_address: str,
        user_agent: str,
        severity: str = "medium",
    ):
        """Log security event for audit trail"""
        try:
            from models.auth import SecurityEvent

            event_descriptions = {
                "login_success": f"Successful login from {ip_address}",
                "login_failed": f"Failed login attempt from {ip_address}",
                "account_locked": "Account locked due to security policy",
                "suspicious_activity": "Suspicious login activity detected",
            }

            security_event = SecurityEvent(
                user_id=user.id,
                tenant_id=user.tenant_id,
                event_type=event_type,
                severity=severity,
                description=event_descriptions.get(
                    event_type, f"Security event: {event_type}"
                ),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db.add(security_event)
            await db.commit()

        except Exception as e:
            logger.error(f"Failed to log security event: {str(e)}")
            # Don't fail the main operation if security logging fails

    async def _handle_failed_attempt(self, db: AsyncSession, user: User):
        """Handle failed login attempt"""
        # Get recent failed attempts
        recent_failures = await db.execute(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.user_id == user.id,
                LoginAttempt.success == False,
                LoginAttempt.attempted_at > get_utc_now() - timedelta(minutes=30),
            )
        )
        failure_count = recent_failures.scalar()

        # Lock account if too many failures
        if failure_count >= self.max_login_attempts:
            await self._lock_account(db, user, "Too many failed login attempts")

    async def _lock_account(self, db: AsyncSession, user: User, reason: str):
        """Lock user account temporarily"""
        lock_until = get_utc_now() + self.lockout_duration

        # Update user settings
        user_settings = user.settings or {}
        user_settings.update(
            {"account_locked_until": lock_until, "lock_reason": reason}
        )

        await db.execute(
            update(User).where(User.id == user.id).values(settings=user_settings)
        )

        logger.warning(f"Account locked for user {user.email}: {reason}")

        # TODO: Send security alert email


class SessionManagementService:
    """Comprehensive session management for enterprise security"""

    def __init__(self):
        self.session_timeout = timedelta(hours=24)  # Session timeout
        self.refresh_token_rotation = True

    async def create_user_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        ip_address: str = None,
        user_agent: str = None,
        device_info: Dict[str, Any] = None,
    ) -> Tuple[UUID, Dict[str, Any]]:
        """Create a new user session with comprehensive tracking"""
        try:
            session_id = uuid4()

            # Get user to retrieve tenant_id - this is the critical fix
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                raise ValueError(f"User not found: {user_id}")

            # Create session record
            session = UserSession(
                id=session_id,
                user_id=user.id,
                tenant_id=user.tenant_id,
                ip_address=ip_address,
                user_agent=user_agent,
                device_info=device_info or {},
                login_time=get_utc_now(),
                last_activity=get_utc_now(),
                expires_at=get_utc_now() + self.session_timeout,
                is_active=True,
            )

            db.add(session)
            await db.commit()
            await db.refresh(session)

            logger.info(f"Created new session {session_id} for user {user_id}")

            return session_id, {
                "session_id": str(session_id),
                "login_time": session.login_time,
                "expires_at": session.expires_at,
                "ip_address": ip_address,
            }

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create user session: {str(e)}")
            raise

    async def validate_session(
        self, db: AsyncSession, session_id: UUID, user_id: UUID
    ) -> bool:
        """Validate session is active and belongs to user"""
        try:
            result = await db.execute(
                select(UserSession).where(
                    UserSession.id == session_id,
                    UserSession.user_id == user_id,
                    UserSession.is_active == True,
                    UserSession.expires_at > get_utc_now(),
                )
            )
            session = result.scalar_one_or_none()

            if session:
                # Update last activity
                session.last_activity = get_utc_now()
                await db.commit()
                return True

            return False

        except Exception as e:
            logger.error(f"Session validation error: {str(e)}")
            return False

    async def revoke_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        user_id: UUID = None,
        reason: str = "user_logout",
    ) -> bool:
        """Revoke a specific session"""
        try:
            query = select(UserSession).where(UserSession.id == session_id)
            if user_id:
                query = query.where(UserSession.user_id == user_id)

            result = await db.execute(query)
            session = result.scalar_one_or_none()

            if session:
                session.is_active = False
                session.logout_time = get_utc_now()
                session.logout_reason = reason
                await db.commit()
                logger.info(f"Revoked session {session_id}, reason: {reason}")
                return True

            return False

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to revoke session: {str(e)}")
            return False

    async def revoke_all_user_sessions(
        self,
        db: AsyncSession,
        user_id: UUID,
        exclude_session_id: UUID = None,
        reason: str = "security_policy",
    ) -> int:
        """Revoke all sessions for a user (except optionally one)"""
        try:
            query = select(UserSession).where(
                UserSession.user_id == user_id, UserSession.is_active == True
            )

            if exclude_session_id:
                query = query.where(UserSession.id != exclude_session_id)

            result = await db.execute(query)
            sessions = result.scalars().all()

            revoked_count = 0
            for session in sessions:
                session.is_active = False
                session.logout_time = get_utc_now()
                session.logout_reason = reason
                revoked_count += 1

            await db.commit()
            logger.info(f"Revoked {revoked_count} sessions for user {user_id}")
            return revoked_count

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to revoke user sessions: {str(e)}")
            return 0

    async def get_active_sessions(
        self, db: AsyncSession, user_id: UUID
    ) -> List[Dict[str, Any]]:
        """Get all active sessions for a user"""
        try:
            result = await db.execute(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.is_active == True,
                    UserSession.expires_at > get_utc_now(),
                )
                .order_by(UserSession.last_activity.desc())
            )
            sessions = result.scalars().all()

            return [
                {
                    "session_id": str(session.id),
                    "ip_address": session.ip_address,
                    "user_agent": session.user_agent,
                    "login_time": session.login_time,
                    "last_activity": session.last_activity,
                    "device_info": session.device_info,
                }
                for session in sessions
            ]

        except Exception as e:
            logger.error(f"Failed to get active sessions: {str(e)}")
            return []

    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        """Clean up expired sessions"""
        try:
            result = await db.execute(
                select(UserSession).where(
                    UserSession.expires_at <= get_utc_now(), UserSession.is_active
                )
            )
            expired_sessions = result.scalars().all()

            cleaned_count = 0
            for session in expired_sessions:
                session.is_active = False
                session.logout_reason = "expired"
                cleaned_count += 1

            await db.commit()
            logger.info(f"Cleaned up {cleaned_count} expired sessions")
            return cleaned_count

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to cleanup expired sessions: {str(e)}")
            return 0


# Initialize services
password_policy_service = PasswordPolicyService()
tenant_status_service = TenantPaymentStatusService()
security_service = SecurityService()
session_service = SessionManagementService()


class AuthService:
    def __init__(self):
        self.user_service = BaseService(User)
        self.session_service = session_service
        self.current_ip: Optional[str] = None
        self.current_user_agent: Optional[str] = None

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def generate_pronounceable_password(self, length: int = 12) -> str:
        """Generate secure, pronounceable passwords"""
        vowels = "aeiou"
        consonants = "bcdfghjklmnpqrstvwxyz"

        # Ensure minimum strength
        while True:
            password = []
            for i in range(length):
                if i % 2 == 0:
                    password.append(secrets.choice(consonants))
                else:
                    password.append(secrets.choice(vowels))

            # Add required character types
            password.append(secrets.choice(string.ascii_uppercase))
            password.append(secrets.choice(string.digits))
            password.append(secrets.choice("!@#$%"))

            secrets.SystemRandom().shuffle(password)
            result = "".join(password)

            # Validate against policy
            is_valid, errors = password_policy_service.validate_password_strength(
                result
            )
            if is_valid:
                return result

    def calculate_password_entropy(self, password: str) -> float:
        """
        Calculate password entropy in bits
        """
        import math

        # Character pool size
        pool_size = 0
        if any(c.islower() for c in password):
            pool_size += 26
        if any(c.isupper() for c in password):
            pool_size += 26
        if any(c.isdigit() for c in password):
            pool_size += 10
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            pool_size += 20

        if pool_size == 0:
            return 0

        entropy = len(password) * math.log2(pool_size)
        return entropy

    def is_password_compromised(self, password: str) -> bool:
        """
        Basic check for common compromised passwords
        """
        common_passwords = {
            "password",
            "123456",
            "password123",
            "admin",
            "qwerty",
            "letmein",
            "welcome",
            "monkey",
            "dragon",
            "master",
        }

        return password.lower() in common_passwords

    def create_access_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None,
        session_id: Optional[UUID] = None,
    ) -> str:
        try:
            """Create access token"""
            to_encode = data.copy()
            if expires_delta:
                expire = get_utc_now() + expires_delta
            else:
                expire = get_utc_now() + timedelta(
                    minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
                )

            # Convert datetime objects to ISO format strings for JSON serialization
            to_encode.update(
                {
                    "exp": expire.timestamp(),  # Use timestamp instead of datetime
                    "type": "access",
                    "iat": get_utc_now().timestamp(),  # Use timestamp
                    "session_id": str(session_id) if session_id else None,
                }
            )

            # Remove any non-serializable objects
            serializable_data = {}
            for key, value in to_encode.items():
                if isinstance(value, (str, int, float, bool, type(None))):
                    serializable_data[key] = value
                elif isinstance(value, datetime):
                    serializable_data[key] = value.timestamp()
                elif isinstance(value, UUID):
                    serializable_data[key] = str(value)
                else:
                    serializable_data[key] = str(
                        value
                    )  # Fallback to string representation

            encoded_jwt = jwt.encode(
                serializable_data, settings.SECRET_KEY, algorithm=settings.ALGORITHM
            )
            return encoded_jwt
        except Exception as e:
            logger.error(f"Failed to create access token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create authentication token",
            )

    def create_refresh_token(self, user_id: str, session_id: UUID) -> Tuple[str, UUID]:
        """Create refresh token with session context and store in database"""
        try:
            token_id = uuid4()
            # Ensure user_id is properly formatted string
            if isinstance(user_id, UUID):
                user_id_str = str(user_id)
            else:
                user_id_str = str(user_id)

            # Ensure session_id is properly formatted string
            session_id_str = str(session_id)

            expire = get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

            refresh_token_data = {
                "jti": str(token_id),
                "sub": user_id_str,
                "exp": expire.timestamp(),  # Use timestamp for consistency
                "type": "refresh",
                "session_id": session_id_str,
                "iat": get_utc_now().timestamp(),
            }

            refresh_token = jwt.encode(
                refresh_token_data, settings.SECRET_KEY, algorithm=settings.ALGORITHM
            )
            return refresh_token, token_id
        except Exception as e:
            logger.error(f"Failed to create refresh token: {str(e)}")
            return None, None

    async def store_refresh_token(
        self,
        db: AsyncSession,
        token_id: UUID,
        user_id: str,
        expires_at: datetime,
        session_id: UUID,
    ) -> None:
        """Enhanced refresh token storage with session management"""
        try:
            # Convert user_id from string to UUID properly
            if isinstance(user_id, str):
                try:
                    user_uuid = UUID(user_id)
                except ValueError:
                    logger.error(f"Invalid user_id format: {user_id}")
                    raise ValueError(f"Invalid user_id format: {user_id}")
            else:
                user_uuid = user_id

            # Get user to retrieve tenant_id
            user = await self.user_service.get(db, user_uuid)
            if not user:
                raise ValueError(f"User not found: {user_id}")

            # Get session to ensure it exists and has tenant_id
            result = await db.execute(
                select(UserSession).where(UserSession.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                raise ValueError(f"Session not found: {session_id}")

            # Use session's tenant_id (which should match user's tenant_id)

            refresh_token = RefreshToken(
                id=token_id,
                tenant_id=session.tenant_id,
                user_id=user_uuid,
                expires_at=ensure_utc(expires_at),
                is_revoked=False,
                session_id=session_id,
                created_at=get_utc_now(),
            )
            db.add(refresh_token)
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to store refresh token: {str(e)}")
            await db.rollback()

    async def revoke_refresh_token(self, db: AsyncSession, token_id: UUID) -> None:
        """Revoke a refresh token"""
        try:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.id == token_id)
            )
            refresh_token = result.scalar_one_or_none()

            if refresh_token:
                setattr(refresh_token, "is_revoked", True)
                await db.commit()
                logger.info(f"Revoked refresh token: {token_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to revoke refresh token: {e}")
            raise

    async def revoke_all_user_tokens(self, db: AsyncSession, user_id: UUID) -> None:
        """Revoke all refresh tokens for a user"""
        try:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.user_id == user_id)
            )
            user_tokens = result.scalars().all()

            for token in user_tokens:
                token.is_revoked = True

            await db.commit()
            logger.info(f"Revoked all refresh tokens for user: {user_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to revoke user tokens: {e}")
            raise

    async def verify_refresh_token(
        self, db: AsyncSession, token: str
    ) -> Tuple[User, UUID]:
        """Verify refresh token and return user"""
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )

            if payload.get("type") != "refresh":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                )

            token_id = UUID(payload.get("jti"))
            user_id = UUID(payload.get("sub"))
            session_id = UUID(payload.get("session_id"))

            # Check if token exists and is not revoked
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.id == token_id,
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked == False,
                    RefreshToken.expires_at > get_utc_now(),
                )
            )
            refresh_token = result.scalar_one_or_none()

            if not refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )

            # Verify session is still valid
            if not await self.session_service.validate_session(db, session_id, user_id):
                await self.revoke_refresh_token(db, token_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired",
                )

            # Get user
            user = await self.user_service.get(db, user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive",
                )

            return user, session_id

        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
            )

    async def authenticate_user(
        self,
        db: AsyncSession,
        email: str,
        password: str,
        tenant: Optional[Tenant] = None,
    ) -> Optional[User]:
        """Authenticate user with optional tenant filtering"""
        try:
            query = select(User).where(User.email == email, User.is_active)

            # If tenant is specified, only search in that tenant
            if tenant:
                query = query.where(User.tenant_id == tenant.id)

            result = await db.execute(query)
            user = result.scalar_one_or_none()

            if user and self.verify_password(password, user.hashed_password):
                return user
            return None
        except Exception as e:
            logger.error(f"Authentication error for {email}: {e}")
            return None

    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get user by email address"""
        try:
            result = await db.execute(
                select(User).where(User.email == email, User.is_active)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None

    def can_user_do_enforced_reset(self, user: User) -> bool:
        """Check if user can perform enforced password reset"""
        # Handle None settings
        user_settings = user.settings or {}

        # Allow enforced reset for:
        # 1. First login (last_login_at is None)
        # 2. Password reset required flag is set
        # 3. Admin has forced password reset
        # 4. Temporary password flag is set
        if (
            user.last_login_at is None
            or user_settings.get("force_password_reset") == True
            or user_settings.get("password_reset_required") == True
            or user_settings.get("temporary_password") == True
        ):
            return True
        return False

    async def verify_password_reset_requirements_cleared(
        self, db: AsyncSession, user_id: UUID
    ) -> bool:
        """Verify that password reset requirements have been cleared"""
        try:
            # Get fresh user instance to avoid caching
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                logger.error(f"User not found for verification: {user_id}")
                return False

            user_settings = user.settings or {}

            # Check if any reset flags are still set to True
            reset_flags = [
                "force_password_reset",
                "password_reset_required",
                "temporary_password",
                "require_reauthentication",
            ]

            for flag in reset_flags:
                if user_settings.get(flag) is True:
                    logger.warning(
                        f"Reset flag still TRUE for user {user_id}: {flag} = {user_settings[flag]}"
                    )
                    return False

            # Also check if account is still locked
            if user_settings.get("account_locked_until"):
                lock_until = datetime.fromisoformat(
                    user_settings["account_locked_until"]
                )
                if lock_until > get_utc_now():
                    logger.warning(f"Account still locked for user {user_id}")
                    return False

            logger.info(
                f"All password reset requirements verified cleared for user: {user.email}"
            )
            return True

        except Exception as e:
            logger.error(f"Error verifying reset requirements for user {user_id}: {e}")
            return False

    async def update_user_password(
        self,
        db: AsyncSession,
        user_id: UUID,
        new_password: str,
        revoke_other_sessions: bool = True,
    ) -> User:
        """Update user password with security logging"""
        try:
            # Validate password strength
            is_valid, errors = password_policy_service.validate_password_strength(
                new_password
            )
            if not is_valid:
                error_message = "Please check your password:\n• " + "\n• ".join(errors)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=error_message,
                )

            # Get user
            user = await self.user_service.get(db, user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            # Check if password was recently used
            if await self._is_password_in_history(db, user, new_password):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="You've used this password recently. Please choose a different one.",
                )

            # Update password
            user.hashed_password = self.get_password_hash(new_password)
            user.updated_at = get_utc_now()

            # Update password history and settings
            await self._update_password_history(db, user, new_password)

            # Revoke other sessions for security (optional)
            if revoke_other_sessions:
                await self.session_service.revoke_all_user_sessions(
                    db, user_id, reason="password_change"
                )
                logger.info(
                    f"Revoked all sessions for user {user_id} after password change"
                )

            await db.commit()
            await db.refresh(user)

            logger.info(f"Password updated for user: {user.email}")
            return user

        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to update password for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update password",
            )

    async def _is_password_in_history(
        self, db: AsyncSession, user: User, new_password: str
    ) -> bool:
        """Check if password was recently used (more lenient)"""
        if "password_history" not in user.settings:
            return False

        history = user.settings["password_history"]

        # Only check the most recent password to avoid frustration
        if history:
            most_recent_hash = history[-1].get("password_hash")
            if most_recent_hash and self.verify_password(
                new_password, most_recent_hash
            ):
                return True

        return False

    async def _update_password_history(
        self, db: AsyncSession, user: User, new_password: str
    ):
        """Update password history for security"""
        try:
            # Initialize password history if not exists
            if "password_history" not in user.settings:
                user.settings["password_history"] = []

            # Add current password to history (limit to last 5 passwords)
            history = user.settings["password_history"]
            history.append(
                {
                    "password_hash": user.hashed_password,  # Store the old hash before update
                    "changed_at": get_utc_now(),
                }
            )

            # Keep only last 5 passwords
            if len(history) > 5:
                history.pop(0)

            user.settings["password_history"] = history
            user.settings["password_changed_at"] = get_utc_now()

            await db.commit()
            await db.refresh(user)
            logger.info(f"Password history updated for user: {user.email}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to update password history: {e}")

    async def clear_password_reset_requirements(self, db: AsyncSession, user_id: UUID):
        """Clear password reset requirements after successful reset"""
        try:
            # Get fresh user instance to avoid caching issues
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                logger.error(
                    f"User not found when clearing reset requirements: {user_id}"
                )
                return

            logger.info(f"Before clearing - user settings: {user.settings}")

            # Initialize settings if None
            if user.settings is None:
                user.settings = {}

            # Clear all reset flags - use direct assignment to ensure change detection
            reset_flags = [
                "force_password_reset",
                "password_reset_required",
                "temporary_password",
                "require_reauthentication",
            ]

            # Create a new dictionary to ensure SQLAlchemy detects changes
            new_settings = dict(user.settings)

            for flag in reset_flags:
                if flag in new_settings:
                    # Set to False for boolean flags, remove for others
                    if flag in [
                        "force_password_reset",
                        "password_reset_required",
                        "temporary_password",
                        "require_reauthentication",
                    ]:
                        new_settings[flag] = False
                    else:
                        del new_settings[flag]

            # Update password changed timestamp
            new_settings["password_changed_at"] = get_utc_now().isoformat()

            # Update last login if it's the first time
            if user.last_login_at is None:
                user.last_login_at = get_utc_now()

            # Use direct assignment to trigger SQLAlchemy change detection
            user.settings = new_settings

            # Force SQLAlchemy to mark the object as modified
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(user, "settings")

            # Explicit commit to ensure changes are saved
            await db.commit()

            # Refresh to get the latest state
            await db.refresh(user)

            logger.info(f"Cleared password reset requirements for user: {user.email}")
            logger.info(f"After clearing - user settings: {user.settings}")

        except Exception as e:
            await db.rollback()
            logger.error(
                f"Failed to clear password reset requirements for user {user_id}: {e}"
            )
            raise

    async def verify_current_password(
        self, db: AsyncSession, user_id: UUID, current_password: str
    ) -> bool:
        """Verify current password for voluntary password changes"""
        try:
            user = await self.user_service.get(db, user_id)
            if not user:
                return False

            return self.verify_password(current_password, user.hashed_password)
        except Exception as e:
            logger.error(f"Error verifying current password: {e}")
            return False

    async def login(
        self,
        db: AsyncSession,
        login_data: UserLogin,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request: Optional[Request] = None,
    ) -> Dict[str, Any]:
        """Enterprise-grade login with comprehensive security checks"""
        try:
            # Input validation
            validation_errors = self._validate_login_input(login_data)
            if validation_errors:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="; ".join(validation_errors),
                )

            tenant = None
            if login_data.tenant_slug:
                tenant = await self._get_tenant_by_slug(db, login_data.tenant_slug)
                if not tenant:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Clinic not found. Please check the clinic name.",
                    )

            # Tenant validation
            tenant = await self._validate_tenant_for_login(db, login_data.tenant_slug)

            # User authentication
            user = await self._authenticate_user_for_login(
                db, login_data.email, login_data.password, tenant
            )

            # Eager load all necessary relationships and attributes
            await db.refresh(
                user,
                [
                    "settings",  # Ensure settings are loaded
                    "tenant",  # Ensure tenant relationship is loaded
                ],
            )

            # Ensure user has proper default values for serialization
            user = self._ensure_user_defaults(user)

            # Check if password reset is required BEFORE other security checks
            if self._should_force_password_reset(user):
                logger.info(f"Password reset required for user: {user.email}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Password reset required for security reasons. Please use the 'Forgot Password' feature.",
                )

            # Security checks
            security_ok, security_message = await security_service.check_login_security(
                db, user, ip_address
            )
            if not security_ok:
                await security_service.record_login_attempt(
                    db, user, False, ip_address, user_agent
                )
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED, detail=security_message
                )

            # Tenant eligibility
            if tenant:
                await self._check_tenant_login_eligibility(db, tenant)

            # User eligibility
            await self._check_user_login_eligibility(user)

            # Verify user belongs to the specified tenant
            if tenant and user.tenant_id != tenant.id:
                await security_service.record_login_attempt(
                    db, user, False, ip_address, user_agent
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not belong to the specified clinic",
                )

            # Create user session
            device_info = self._extract_device_info(request)
            session_id, session_data = await self.session_service.create_user_session(
                db, user.id, ip_address, user_agent, device_info
            )

            # Create tokens with session context
            tokens = await self._create_login_tokens(db, user, session_id)

            # Record successful login
            await security_service.record_login_attempt(
                db, user, True, ip_address, user_agent
            )

            # Update login analytics
            await self._update_login_analytics(db, user, tenant)

            logger.info(
                f"Successful login for user: {user.email} from IP: {ip_address}, session: {session_id}"
            )

            return {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": "bearer",
                "user": user,
                "tenant": (
                    {
                        "id": str(tenant.id) if tenant else str(user.tenant_id),
                        "name": tenant.name if tenant else user.tenant.name,
                        "slug": tenant.slug if tenant else user.tenant.slug,
                        "tier": tenant.tier if tenant else user.tenant.tier,
                        "status": tenant.status if tenant else user.tenant.status,
                    }
                    if tenant or hasattr(user, "tenant")
                    else None
                ),
                "session_id": str(session_id),
                "session_data": session_data,
                "password_reset_required": self._should_force_password_reset(user),
            }

        except HTTPException as he:
            # Handle HTTP exceptions with proper logging
            await self._handle_login_exception(
                db, login_data.email, ip_address, user_agent, he
            )
            raise
        except Exception as e:
            # Handle unexpected exceptions
            await self._handle_login_exception(
                db, login_data.email, ip_address, user_agent, e
            )
            logger.error(f"Unexpected login error for {login_data.email}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login failed due to a server error. Please try again.",
            )

    async def _get_tenant_by_slug(
        self, db: AsyncSession, tenant_slug: str
    ) -> Optional[Tenant]:
        """Get tenant by slug without tenant context"""
        try:
            result = await db.execute(
                select(Tenant).where(
                    Tenant.slug == tenant_slug,
                    Tenant.status == "active",  # Only active tenants
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting tenant by slug {tenant_slug}: {e}")
            return None

    def _validate_login_input(self, login_data: UserLogin) -> List[str]:
        """Comprehensive login input validation"""
        errors = []

        if not login_data.email or not login_data.email.strip():
            errors.append("Email is required")
        elif "@" not in login_data.email:
            errors.append("Valid email address is required")

        if not login_data.password:
            errors.append("Password is required")
        elif len(login_data.password) < 1:  # Minimum length check
            errors.append("Password must not be empty")

        # Rate limiting check (could be implemented with Redis)
        # TODO: Implement IP-based rate limiting

        return errors

    def _extract_device_info(self, request: Optional[Request]) -> Dict[str, Any]:
        """Extract device information from request"""
        if not request:
            return {}

        try:
            user_agent = request.headers.get("user-agent", "")
            return {
                "user_agent": user_agent,
                "accept_language": request.headers.get("accept-language"),
                "accept_encoding": request.headers.get("accept-encoding"),
                "platform": self._detect_platform(user_agent),
            }
        except Exception as e:
            logger.warning(f"Could not extract device info: {e}")
            return {}

    def _detect_platform(self, user_agent: str) -> str:
        """Detect platform from user agent"""
        user_agent = user_agent.lower()
        if "windows" in user_agent:
            return "windows"
        elif "mac" in user_agent:
            return "macos"
        elif "linux" in user_agent:
            return "linux"
        elif "android" in user_agent:
            return "android"
        elif "iphone" in user_agent or "ipad" in user_agent:
            return "ios"
        else:
            return "unknown"

    async def _validate_tenant_for_login(
        self, db: AsyncSession, tenant_slug: Optional[str]
    ) -> Optional[Tenant]:
        """Validate and retrieve tenant for login"""
        if not tenant_slug:
            return None

        try:
            result = await db.execute(
                select(Tenant).where(
                    Tenant.slug
                    == tenant_slug
                    # Don't filter by status here - we want to provide specific error messages
                )
            )
            tenant = result.scalar_one_or_none()

            if not tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Clinic not found. Please check the clinic name or contact support.",
                )

            return tenant

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error validating tenant {tenant_slug}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error validating clinic. Please try again.",
            )

    async def _authenticate_user_for_login(
        self, db: AsyncSession, email: str, password: str, tenant: Optional[Tenant]
    ) -> User:
        """Authenticate user with comprehensive error handling"""
        try:
            # Build query based on tenant context
            query = select(User).where(
                User.email == email,
                User.is_active,  # Only active users can login
            )

            if tenant:
                query = query.where(User.tenant_id == tenant.id)

            result = await db.execute(query)
            user = result.scalar_one_or_none()

            if not user:
                # Don't reveal whether email exists or not
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )

            # Verify password
            if not self.verify_password(password, user.hashed_password):
                # Log failed attempt for security monitoring
                logger.warning(f"Failed login attempt for user: {email}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )

            return user

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error authenticating user {email}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication error. Please try again.",
            )

    async def _check_tenant_login_eligibility(
        self, db: AsyncSession, tenant: Optional[Tenant]
    ) -> None:
        """Enhanced tenant eligibility checking"""
        if not tenant:
            return

        can_login, message = await tenant_status_service.can_tenant_accept_logins(
            db, tenant
        )

        if not can_login:
            # Map to appropriate HTTP status codes
            status_map = {
                "cancelled": status.HTTP_410_GONE,
                "suspended": status.HTTP_403_FORBIDDEN,
                "trial ended": status.HTTP_402_PAYMENT_REQUIRED,
                "limit": status.HTTP_402_PAYMENT_REQUIRED,
                "expired": status.HTTP_402_PAYMENT_REQUIRED,
                "overdue": status.HTTP_402_PAYMENT_REQUIRED,
            }

            status_code = status.HTTP_403_FORBIDDEN
            for key, code in status_map.items():
                if key in message.lower():
                    status_code = code
                    break

            raise HTTPException(status_code=status_code, detail=message)

    async def _check_user_login_eligibility(self, user: User) -> None:
        """Comprehensive user eligibility checking"""
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has been deactivated. Please contact your clinic administrator.",
            )

        # Check for forced password reset
        if self._should_force_password_reset(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password reset required for security reasons. Please use the 'Forgot Password' feature.",
            )

        # Check if account requires reauthentication
        if user.settings.get("require_reauthentication"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Additional verification required. Please contact support.",
            )

    def _should_force_password_reset(self, user: User) -> bool:
        """Check if password reset should be forced - USING SAFE HELPER"""
        try:
            # First login (user was created but never logged in)
            if user.last_login_at is None:
                logger.info(f"First login detected for user: {user.email}")
                return True

            # Get settings safely
            user_settings = self._get_user_settings_safe(user)

            # Admin forced reset
            if user_settings.get("force_password_reset") == True:
                logger.info(f"Admin forced password reset for user: {user.email}")
                return True

            # Security policy requires reset
            if user_settings.get("password_reset_required") == True:
                logger.info(
                    f"Security policy requires password reset for user: {user.email}"
                )
                return True

            # Check if this is a system-created user with temporary password
            if user_settings.get("temporary_password") == True:
                logger.info(f"Temporary password detected for user: {user.email}")
                return True

            # Password expiration check
            password_changed_at = user_settings.get("password_changed_at")
            if password_changed_at:
                try:
                    if isinstance(password_changed_at, str):
                        changed_dt = datetime.fromisoformat(
                            password_changed_at.replace("Z", "+00:00")
                        )
                    else:
                        changed_dt = password_changed_at

                    password_age = get_utc_now() - changed_dt
                    if password_age.days > password_policy_service.max_age_days:
                        logger.info(f"Password expired for user: {user.email}")
                        return True
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Error parsing password_changed_at for user {user.email}: {e}"
                    )

            return False

        except Exception as e:
            logger.error(
                f"Error checking password reset requirement for user {user.email}: {e}"
            )
            return False

    def _get_user_settings_safe(self, user: User) -> Dict[str, Any]:
        """Safely get user settings without triggering database access"""
        try:
            # Direct attribute access
            settings = getattr(user, "settings", None)
            if settings is None:
                return {}

            # If it's a dict, return it directly
            if isinstance(settings, dict):
                return settings

            # If it's a string (JSON), parse it
            if isinstance(settings, str):
                import json

                return json.loads(settings)

            # Fallback to empty dict
            return {}
        except Exception as e:
            logger.warning(
                f"Error accessing user settings for {getattr(user, 'email', 'unknown')}: {e}"
            )
            return {}

    async def get_user_by_email_and_tenant(
        self, db: AsyncSession, email: str, tenant_slug: str
    ) -> Optional[User]:
        """Get user by email and tenant slug (for enforced password resets)"""
        try:
            # First get the tenant by slug
            result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            tenant = result.scalar_one_or_none()

            if not tenant:
                return None

            # Then get user by email and tenant ID
            result = await db.execute(
                select(User).where(
                    User.email == email, User.tenant_id == tenant.id, User.is_active
                )
            )
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Error getting user by email and tenant: {e}")
            return None

    async def _update_login_analytics(
        self, db: AsyncSession, user: User, tenant: Optional[Tenant]
    ):
        """Update login analytics for business intelligence"""
        try:
            # Update user's login count and last login
            user.last_login_at = get_utc_now()

            # Initialize login_count in settings if not exists
            if user.settings is None:
                user.settings = {}

            current_count = user.settings.get("login_count", 0)
            user.settings["login_count"] = current_count + 1
            user.settings["last_login_ip"] = getattr(self, "current_ip", "unknown")
            user.settings["last_login_user_agent"] = getattr(
                self, "current_user_agent", "unknown"
            )

            # Update tenant analytics if available
            if tenant:
                # Update tenant's current user count if this is a new active user
                if user.is_active and not user.last_login_at:
                    tenant.current_user_count = (tenant.current_user_count or 0) + 1

                # Update last usage update timestamp
                tenant.last_usage_update = get_utc_now()

            await db.commit()
            logger.info(f"Updated login analytics for user: {user.email}")

        except Exception as e:
            logger.error(f"Error updating login analytics: {e}")
            # Don't fail the login if analytics update fails
            await db.rollback()  # Rollback to avoid partial updates

    async def _create_login_tokens(
        self, db: AsyncSession, user: User, session_id: UUID
    ) -> Dict[str, str]:
        """Create secure login tokens with session management"""

        # Create access token with enhanced claims
        access_token = self.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
                "session_id": str(session_id),
                "login_time": get_utc_now(),
                "auth_method": "password",
            },
            session_id=session_id,
        )

        # Create and store refresh token with session context
        refresh_token, token_id = self.create_refresh_token(str(user.id), session_id)
        expires_at = get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        # Store refresh token with session info
        await self.store_refresh_token(
            db, token_id, getattr(user, "id"), expires_at, session_id
        )

        # Update user's last login with UTC time
        user.last_login_at = get_utc_now()
        await db.commit()

        # Eager load relationships
        await db.refresh(user, ["tenant"])

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "session_id": str(session_id),
        }

    async def create_tenant_admin_user(
        self,
        db: AsyncSession,
        tenant: Tenant,
        email: str,
        background_tasks: BackgroundTasks,
    ) -> User:
        """Create default admin user for new tenant"""
        # Generate temporary password
        temp_password = self.generate_pronounceable_password()

        try:
            # Create UserCreate instance with all required fields
            user_data = UserCreate(
                email=email,
                password=temp_password,
                first_name="Clinic",
                last_name="Admin",
                contact_number="",  # Required but can be empty
                gender=GenderEnum.OTHER,
                role=StaffRole.ADMIN,
                specialization=None,
                license_number=None,
                employee_id=None,
                permissions={
                    "Admin": [
                        "user_manage",
                        "patient_manage",
                        "appointment_manage",
                        "prescription_manage",
                        "medical_records_manage",
                        "services_manage",
                        "invoice_manage",
                        "treatment_manage",
                        "report_view",
                        "settings_manage",
                    ]
                },
                is_active=True,
            )

            user = await self.create_user(
                db, user_data, background_tasks, str(tenant.slug), str(tenant.id)
            )

            logger.info(
                f"Created tenant admin user: {email} for tenant: {tenant.name} with password: {temp_password}"
            )

            return user

        except Exception as e:
            logger.error(f"Failed to create tenant admin user: {e}")
            raise

    async def send_tenant_welcome_email_sync(
        self,
        db: AsyncSession,
        user_id: str,
        temp_password: str,
        tenant_slug: str,
        default_admin_user: bool = True,
    ):
        """Async wrapper to send welcome tenant email (background task)"""
        asyncio.create_task(
            self._send_tenant_welcome_email_async(
                db,
                UUID(user_id),
                temp_password,
                tenant_slug,
                default_admin_user,
            )
        )

    async def _send_tenant_welcome_email_async(
        self,
        db: AsyncSession,
        user_id: UUID,
        temp_password: str,
        tenant_slug: str,
        default_admin_user: bool = True,
    ):
        """Async function for sending tenant welcome email"""

        async with AsyncSessionLocal() as session:
            try:
                # Use a fresh session for the background task
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if not user:
                    logger.error(f"User not found for welcome email: {user_id}")
                    return

                # Also get tenant info for the email
                result = await session.execute(
                    select(Tenant).where(Tenant.slug == tenant_slug)
                )
                tenant = result.scalar_one_or_none()

                await email_service.send_tenant_welcome_email(
                    user_email=str(user.email),
                    user_name=f"{user.first_name} {user.last_name}",
                    temp_password=temp_password,
                    tenant_slug=str(tenant.slug),
                )

                if not default_admin_user:
                    await email_integration_service.send_welcome_email_to_staff(
                        db, user_id, temp_password
                    )

            except Exception as e:
                logger.error(
                    f"Error in background welcome email for user {user_id}: {e}"
                )

    async def refresh_tokens(
        self, db: AsyncSession, refresh_token: str
    ) -> Dict[str, Any]:
        """Refresh access token using refresh token with session management"""
        user, session_id = await self.verify_refresh_token(db, refresh_token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
            )

        # Create new access token
        access_token = self.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
                "session_id": str(session_id),
            },
            session_id=session_id,
        )

        # Token rotation for security
        if settings.REFRESH_TOKEN_ROTATION:
            # Revoke old token
            payload = jwt.decode(
                refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            old_token_id = UUID(payload.get("jti"))
            await self.revoke_refresh_token(db, old_token_id)

            # Create new refresh token
            new_refresh_token, new_token_id = self.create_refresh_token(
                str(user.id), session_id
            )
            expires_at = get_utc_now() + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
            await self.store_refresh_token(
                db, new_token_id, str(user.id), expires_at, session_id
            )

            return {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "session_id": str(session_id),
            }
        else:
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "session_id": str(session_id),
            }

    async def logout(
        self,
        db: AsyncSession,
        refresh_token: Optional[str] = None,
        session_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Comprehensive logout with session management"""
        try:
            result = {"sessions_revoked": 0, "tokens_revoked": 0}

            # If refresh token provided, revoke it and get session info
            if refresh_token:
                try:
                    payload = jwt.decode(
                        refresh_token,
                        settings.SECRET_KEY,
                        algorithms=[settings.ALGORITHM],
                    )
                    token_id = UUID(payload.get("jti"))
                    session_id_from_token = UUID(payload.get("session_id"))
                    user_id_from_token = UUID(payload.get("sub"))

                    # Use the session_id from token if not provided
                    if not session_id:
                        session_id = session_id_from_token
                    if not user_id:
                        user_id = user_id_from_token

                    await self.revoke_refresh_token(db, token_id)
                    result["tokens_revoked"] += 1

                except JWTError:
                    logger.warning("Invalid refresh token during logout")

            # Revoke specific session if provided
            if session_id and user_id:
                if await self.session_service.revoke_session(
                    db, session_id, user_id, "user_logout"
                ):
                    result["sessions_revoked"] += 1

            # If no specific session but we have user_id, revoke current session
            elif user_id and session_id:
                if await self.session_service.revoke_session(
                    db, session_id, user_id, "user_logout"
                ):
                    result["sessions_revoked"] += 1

            logger.info(f"Logout completed: {result}")
            return result

        except Exception as e:
            logger.error(f"Logout error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Logout failed",
            )

    async def logout_all(self, db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
        """Logout user from all devices with session management"""
        try:
            # Revoke all sessions
            sessions_revoked = await self.session_service.revoke_all_user_sessions(
                db, user_id, reason="security_policy"
            )

            # Revoke all refresh tokens
            await self.revoke_all_user_tokens(db, user_id)

            result = {
                "sessions_revoked": sessions_revoked,
                "tokens_revoked": sessions_revoked,  # Estimate
                "message": f"Logged out from {sessions_revoked} devices",
            }

            logger.info(f"Force logout completed for user {user_id}: {result}")
            return result

        except Exception as e:
            logger.error(f"Force logout error for user {user_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to logout from all devices",
            )

    async def get_current_user_and_session(
        self,
        db: AsyncSession = Depends(get_db),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> Tuple[User, UUID]:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": True},  # Ensure expiration is verified
            )

            if payload.get("type") != "access":
                raise credentials_exception

            user_id: str = payload.get("sub")
            session_id: str = payload.get("session_id")

            if user_id is None or session_id is None:
                raise credentials_exception

        except jwt.ExpiredSignatureError:
            # Token has expired - check if we can refresh it
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired. Please refresh your token or log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        except JWTError:
            raise credentials_exception

        user = await self.user_service.get(db, UUID(user_id))
        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
            )

        # Validate session
        if not await self.session_service.validate_session(
            db, UUID(session_id), user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
            )

        return user, UUID(session_id)

    async def get_current_user(
        self,
        db: AsyncSession = Depends(get_db),
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> User:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": True},  # Ensure expiration is verified
            )

            if payload.get("type") != "access":
                raise credentials_exception

            user_id: str = payload.get("sub")
            session_id: str = payload.get("session_id")

            if user_id is None or session_id is None:
                raise credentials_exception

        except jwt.ExpiredSignatureError:
            # Token has expired - check if we can refresh it
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired. Please refresh your token or log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        except JWTError:
            raise credentials_exception

        user = await self.user_service.get(db, UUID(user_id))
        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
            )

        # Validate session
        if not await self.session_service.validate_session(
            db, UUID(session_id), user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
            )

        return user

    def _ensure_user_defaults(self, user: User) -> User:
        """Ensure user object has proper default values for serialization"""
        # Ensure work_schedule is never None
        if getattr(user, "work_schedule", None) is None:
            user.work_schedule = {}

        # Ensure settings is never None
        if getattr(user, "settings", None) is None:
            user.settings = {}

        # Ensure permissions is never None
        if getattr(user, "permissions", None) is None:
            user.permissions = {}

        return user

    async def create_user(
        self,
        db: AsyncSession,
        user_data: UserCreate,
        background_tasks: BackgroundTasks,
        tenant_slug: Optional[str] = None,
        tenant_id: Optional[str] = None,
        create_default_user: bool = True,
    ) -> User:
        """Create user - automatically uses current tenant context if not specified"""
        try:
            default_admin_user: bool = create_default_user
            # Validate password strength
            is_valid, errors = password_policy_service.validate_password_strength(
                user_data.password
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Password does not meet security requirements: "
                    + "; ".join(errors),
                )

            # Check for existing user across all tenants
            result = await db.execute(select(User).where(User.email == user_data.email))
            existing_user = result.scalar_one_or_none()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists",
                )

            hashed_password = self.get_password_hash(user_data.password)
            user_data_dict = user_data.model_dump(exclude={"password"})
            user_data_dict["hashed_password"] = hashed_password

            # CRITICAL FIX: Proper tenant_id handling with UUID conversion
            final_tenant_id = None
            if tenant_id:
                # Use provided tenant_id - ensure it's a proper UUID
                try:
                    final_tenant_id = self.safe_uuid_conversion(tenant_id)
                except ValueError as e:
                    logger.error(f"Invalid tenant_id format: {tenant_id}, error: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid tenant ID format",
                    )
            else:
                # Try to get tenant context from database session
                from db.database import tenant_id_var

                current_tenant_id = tenant_id_var.get()
                if current_tenant_id:
                    try:
                        final_tenant_id = self.safe_uuid_conversion(current_tenant_id)
                    except ValueError as e:
                        logger.error(
                            f"Invalid current_tenant_id format: {current_tenant_id}, error: {e}"
                        )
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid tenant context",
                        )
                else:
                    # For system operations (like tenant creation), we need tenant_id
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Tenant context is required to create user",
                    )

            if not final_tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tenant context is required to create user",
                )

            user_data_dict["tenant_id"] = final_tenant_id

            # Handle work_schedule conversion safely
            if "work_schedule" in user_data_dict and user_data_dict["work_schedule"]:
                if isinstance(user_data_dict["work_schedule"], UserWorkSchedule):
                    user_data_dict["work_schedule"] = user_data_dict[
                        "work_schedule"
                    ].model_dump()

            # Ensure proper defaults for dentist-specific fields
            if user_data_dict.get("role") in [
                StaffRole.DENTIST,
                StaffRole.DENTAL_THERAPIST,
                StaffRole.HYGIENIST,
            ]:
                user_data_dict.setdefault("max_patients", 50)
                user_data_dict.setdefault("is_accepting_new_patients", True)
                user_data_dict.setdefault("availability_schedule", {})

            # CRITICAL FIX: Initialize settings properly
            user_settings = user_data_dict.get("settings", {})
            if not isinstance(user_settings, dict):
                user_settings = {}

            # Set security defaults based on user type
            if default_admin_user:
                security_defaults = {
                    "login_count": 0,
                    "account_locked_until": None,
                    "temporary_password": True,
                    "force_password_reset": True,  # Force reset on first login
                    "password_changed_at": get_utc_now().isoformat(),
                }
            else:
                security_defaults = {
                    "login_count": 0,
                    "account_locked_until": None,
                    "temporary_password": False,
                    "force_password_reset": False,
                    "password_changed_at": get_utc_now().isoformat(),
                }

            # Merge settings safely
            for key, value in security_defaults.items():
                if key not in user_settings:
                    user_settings[key] = value

            user_data_dict["settings"] = user_settings

            # Ensure other required fields have proper defaults
            user_data_dict.setdefault("permissions", {})
            user_data_dict.setdefault("work_schedule", {})
            user_data_dict.setdefault("is_active", True)
            user_data_dict.setdefault("is_verified", False)
            user_data_dict.setdefault("is_available", True)

            # CRITICAL FIX: Convert all UUID fields to proper UUID objects
            # Ensure all UUID fields are properly converted
            uuid_fields = ["tenant_id"]  # Add other UUID fields if needed
            for field in uuid_fields:
                if field in user_data_dict and user_data_dict[field]:
                    if isinstance(user_data_dict[field], str):
                        try:
                            user_data_dict[field] = UUID(user_data_dict[field])
                        except ValueError as e:
                            logger.error(
                                f"Invalid UUID format for {field}: {user_data_dict[field]}, error: {e}"
                            )
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid {field} format",
                            )

            # Log the data we're about to create (excluding password)
            debug_data = user_data_dict.copy()
            if "hashed_password" in debug_data:
                debug_data["hashed_password"] = "***"
            logger.debug(f"Creating user with data: {debug_data}")

            # Create user with all prepared data
            user = User(**user_data_dict)
            db.add(user)
            await db.commit()
            await db.refresh(user)

            logger.info(f"Created new user: {user.email} in tenant: {user.tenant_id}")

            # Send welcome email with setup instructions
            background_tasks.add_task(
                self.send_tenant_welcome_email_sync,
                db,
                str(user.id),
                user_data.password,
                tenant_slug,
                default_admin_user,
            )

            return user

        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create user: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user account",
            )

    def safe_uuid_conversion(self, uuid_value) -> UUID:
        """Safely convert various UUID formats to UUID object"""
        if uuid_value is None:
            raise ValueError("UUID value cannot be None")

        if isinstance(uuid_value, UUID):
            return uuid_value

        if isinstance(uuid_value, str):
            try:
                return UUID(uuid_value)
            except ValueError as e:
                raise ValueError(f"Invalid UUID string format: {uuid_value}") from e

        # Handle asyncpg UUID objects or other types
        try:
            return UUID(str(uuid_value))
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Cannot convert {type(uuid_value)} to UUID: {uuid_value}"
            ) from e

    async def _handle_login_exception(
        self,
        db: AsyncSession,
        email: str,
        ip_address: str,
        user_agent: str,
        error: Exception,
    ):
        """Handle login exceptions with proper cleanup and logging"""
        try:
            # Try to get user for security logging
            user = await self.get_user_by_email(db, email)
            if user:
                # Record failed login attempt
                await security_service.record_login_attempt(
                    db, user, False, ip_address, user_agent
                )

                # Increment failed login attempts counter
                if hasattr(user, "failed_login_attempts"):
                    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                    user.last_failed_login = get_utc_now()

                # Check if account should be locked due to too many failed attempts
                if user.failed_login_attempts >= 5:  # Lock after 5 failed attempts
                    lock_until = get_utc_now() + timedelta(minutes=30)
                    if user.settings is None:
                        user.settings = {}
                    user.settings.update(
                        {
                            "account_locked_until": lock_until.isoformat(),
                            "lock_reason": "Too many failed login attempts",
                        }
                    )
                    logger.warning(
                        f"Account locked for user {email} due to too many failed attempts"
                    )

                await db.commit()

            # Log the exception with context
            error_context = {
                "email": email,
                "ip_address": ip_address,
                "user_agent": (
                    user_agent[:200] if user_agent else None
                ),  # Truncate long user agents
                "error_type": type(error).__name__,
                "error_message": str(error),
            }

            if isinstance(error, HTTPException):
                logger.warning(f"Login HTTP exception: {error_context}")
            else:
                logger.error(f"Login exception: {error_context}", exc_info=True)

        except Exception as log_error:
            logger.error(f"Error handling login exception for {email}: {log_error}")
            # Don't let exception handling break the main error flow
            await db.rollback()


auth_service = AuthService()
