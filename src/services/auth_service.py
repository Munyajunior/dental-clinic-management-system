# src/services/auth_service.py (Enhanced)
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, func, update
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
import httpx
from db.database import get_db
from core.config import settings
from models.user import StaffRole, GenderEnum
from models.user import User
from models.tenant import Tenant, TenantStatus, TenantTier, BillingCycle
from models.auth import RefreshToken, LoginAttempt
from schemas.user_schemas import UserLogin, UserCreate
from services.email_service import email_service
from services.usage_service import UsageService
from services.payment_service import PaymentService
from utils.logger import setup_logger
from .base_service import BaseService
import secrets
import string
import hashlib

logger = setup_logger("AUTH_SERVICE")

security = HTTPBearer()
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class PasswordPolicyService:
    """Enterprise password policy enforcement"""

    def __init__(self):
        self.min_length = 8
        self.require_uppercase = True
        self.require_lowercase = True
        self.require_numbers = True
        self.require_special_chars = True
        self.max_age_days = 90  # Password expiration
        self.history_size = 5  # Remember last 5 passwords

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
        if self.calculate_password_entropy(password) < 60:  # bits
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
        }
        return password.lower() in common_passwords

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
            pool_size += 32  # Extended special characters

        if pool_size == 0:
            return 0

        entropy = len(password) * math.log2(pool_size)
        return entropy

    def is_password_expired(self, user: User) -> bool:
        """Check if user's password has expired"""
        if not user.updated_at:
            return False

        password_age = datetime.utcnow() - user.updated_at
        return password_age.days > self.max_age_days


class TenantStatusService:
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
        current_time = datetime.utcnow()

        # Status-based checks
        status_checks = {
            TenantStatus.CANCELLED: (
                False,
                "This clinic account has been cancelled. Please contact support.",
            ),
            TenantStatus.SUSPENDED: (
                False,
                "This clinic account has been suspended due to policy violation. Please contact support.",
            ),
            TenantStatus.PENDING: (True, "Account pending activation"),
        }

        if tenant.status in status_checks:
            return status_checks[tenant.status]

        # Trial account checks
        if tenant.status == TenantStatus.TRIAL:
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
        elif tenant.status == TenantStatus.ACTIVE:
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
        elif tenant.status == TenantStatus.GRACE_PERIOD:
            if (
                tenant.grace_period_ends_at
                and tenant.grace_period_ends_at < current_time
            ):
                return (
                    False,
                    "Grace period has ended. Please update your payment method to continue.",
                )
            return True, "Account in grace period"

        return False, "Unknown account status. Please contact support."

    async def _check_trial_limits(
        self, db: AsyncSession, tenant: Tenant
    ) -> Tuple[bool, str]:
        """Check trial account limits with real usage data"""
        try:
            # Get current usage
            usage = await self.usage_service.get_tenant_usage(db, tenant.id)

            tier_features = self.get_tenant_tier_features(tenant.tier)

            # Check user limit
            if usage.active_users >= tier_features["max_users"]:
                return (
                    False,
                    "Trial user limit reached. Please upgrade to add more users.",
                )

            # Check patient limit
            if usage.patient_count >= tier_features["max_patients"]:
                return (
                    False,
                    "Trial patient limit reached. Please upgrade to add more patients.",
                )

            # Check storage limit
            if usage.storage_used_gb >= tier_features["max_storage_gb"]:
                return (
                    False,
                    "Trial storage limit reached. Please upgrade for more storage.",
                )

            # Check API calls
            if usage.api_calls_this_month >= tier_features.get("max_api_calls", 1000):
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
                        or tenant.grace_period_ends_at < datetime.utcnow()
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
        # Check if account is locked
        if user.settings.get("account_locked_until"):
            lock_until = datetime.fromisoformat(user.settings["account_locked_until"])
            if lock_until > datetime.utcnow():
                remaining = lock_until - datetime.utcnow()
                return (
                    False,
                    f"Account temporarily locked. Try again in {remaining.seconds // 60} minutes.",
                )

        # Check for suspicious activity
        if await self._has_suspicious_activity(db, user, ip_address):
            await self._lock_account(db, user, "Suspicious activity detected")
            return False, "Suspicious activity detected. Account temporarily locked."

        return True, "Security checks passed"

    async def _has_suspicious_activity(
        self, db: AsyncSession, user: User, ip_address: str
    ) -> bool:
        """Detect suspicious login patterns"""
        # Check for multiple failed attempts from different IPs
        recent_failures = await db.execute(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.user_id == user.id,
                LoginAttempt.success == False,
                LoginAttempt.attempted_at > datetime.utcnow() - timedelta(hours=1),
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
        login_attempt = LoginAttempt(
            user_id=user.id,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
            attempted_at=datetime.utcnow(),
        )
        db.add(login_attempt)

        if not success:
            await self._handle_failed_attempt(db, user)

        await db.commit()

    async def _handle_failed_attempt(self, db: AsyncSession, user: User):
        """Handle failed login attempt"""
        # Get recent failed attempts
        recent_failures = await db.execute(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.user_id == user.id,
                LoginAttempt.success == False,
                LoginAttempt.attempted_at > datetime.utcnow() - timedelta(minutes=30),
            )
        )
        failure_count = recent_failures.scalar()

        # Lock account if too many failures
        if failure_count >= self.max_login_attempts:
            await self._lock_account(db, user, "Too many failed login attempts")

    async def _lock_account(self, db: AsyncSession, user: User, reason: str):
        """Lock user account temporarily"""
        lock_until = datetime.utcnow() + self.lockout_duration

        # Update user settings
        user_settings = user.settings or {}
        user_settings.update(
            {"account_locked_until": lock_until.isoformat(), "lock_reason": reason}
        )

        await db.execute(
            update(User).where(User.id == user.id).values(settings=user_settings)
        )

        logger.warning(f"Account locked for user {user.email}: {reason}")

        # TODO: Send security alert email


# Initialize services
password_policy_service = PasswordPolicyService()
tenant_status_service = TenantStatusService()
security_service = SecurityService()


class AuthService:
    def __init__(self):
        self.user_service = BaseService(User)

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
        self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None
    ) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )

        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(
            to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )
        return encoded_jwt

    def create_refresh_token(self, user_id: UUID) -> Tuple[str, UUID]:
        """Create refresh token and store in database"""
        token_id = uuid4()
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        refresh_token_data = {
            "jti": str(token_id),
            "sub": str(user_id),
            "exp": expire,
            "type": "refresh",
        }

        refresh_token = jwt.encode(
            refresh_token_data, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )
        return refresh_token, token_id

    async def store_refresh_token(
        self,
        db: AsyncSession,
        token_id: UUID,
        user_id: UUID,
        expires_at: datetime,
        session_id: UUID = None,
    ) -> None:
        """Enhanced refresh token storage with session management"""
        refresh_token = RefreshToken(
            id=token_id,
            user_id=user_id,
            expires_at=expires_at,
            is_revoked=False,
            session_id=session_id,
            created_at=datetime.utcnow(),
        )
        db.add(refresh_token)
        await db.commit()

    async def revoke_refresh_token(self, db: AsyncSession, token_id: UUID) -> None:
        """Revoke a refresh token"""
        await db.execute(delete(RefreshToken).where(RefreshToken.id == token_id))
        await db.commit()

    async def revoke_all_user_tokens(self, db: AsyncSession, user_id: UUID) -> None:
        """Revoke all refresh tokens for a user"""
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await db.commit()

    async def verify_refresh_token(
        self, db: AsyncSession, token: str
    ) -> Optional[User]:
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

            # Check if token exists and is not revoked
            result = await db.execute(
                select(RefreshToken).where(
                    RefreshToken.id == token_id,
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked == False,
                    RefreshToken.expires_at > datetime.utcnow(),
                )
            )
            refresh_token = result.scalar_one_or_none()

            if not refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )

            # Get user
            user = await self.user_service.get(db, user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive",
                )

            return user

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
        # Allow enforced reset for:
        # 1. First login (last_login_at is None)
        # 2. Password reset required flag is set
        # 3. Admin has forced password reset
        return (
            user.last_login_at is None
            or user.settings.get("force_password_reset", False)
            or user.settings.get("password_reset_required", False)
        )

    async def update_user_password(
        self, db: AsyncSession, user_id: UUID, new_password: str
    ) -> User:
        """Update user password with security logging"""
        try:
            # Validate password strength
            is_valid, errors = password_policy_service.validate_password_strength(
                new_password
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Password does not meet security requirements: "
                    + "; ".join(errors),
                )

            # Get user
            user = await self.user_service.get(db, user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            # Update password
            user.hashed_password = self.get_password_hash(new_password)
            user.updated_at = datetime.utcnow()

            # Update password history and settings
            await self._update_password_history(db, user, new_password)

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

    async def _update_password_history(
        self, db: AsyncSession, user: User, new_password: str
    ):
        """Update password history for security"""
        # Initialize password history if not exists
        if "password_history" not in user.settings:
            user.settings["password_history"] = []

        # Add current password to history (limit to last 5 passwords)
        history = user.settings["password_history"]
        history.append(
            {
                "password_hash": user.hashed_password,  # Store the old hash before update
                "changed_at": datetime.utcnow().isoformat(),
            }
        )

        # Keep only last 5 passwords
        if len(history) > 5:
            history.pop(0)

        user.settings["password_history"] = history
        user.settings["password_changed_at"] = datetime.utcnow().isoformat()

    async def clear_password_reset_requirements(self, db: AsyncSession, user_id: UUID):
        """Clear password reset requirements after successful reset"""
        try:
            user = await self.user_service.get(db, user_id)
            if not user:
                return

            # Clear reset flags
            if "force_password_reset" in user.settings:
                user.settings["force_password_reset"] = False
            if "password_reset_required" in user.settings:
                user.settings["password_reset_required"] = False

            # Update last login if it's the first time
            if user.last_login_at is None:
                user.last_login_at = datetime.utcnow()

            await db.commit()
            logger.info(f"Cleared password reset requirements for user: {user.email}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to clear password reset requirements: {e}")

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
        ip_address: str = None,
        user_agent: str = None,
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

            # Tenant validation
            tenant = await self._validate_tenant_for_login(db, login_data.tenant_slug)

            # User authentication
            user = await self._authenticate_user_for_login(
                db, login_data.email, login_data.password, tenant
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
            await self._check_tenant_login_eligibility(db, tenant)

            # User eligibility
            await self._check_user_login_eligibility(user)

            # Tenant-user relationship verification
            if tenant and user.tenant_id != tenant.id:
                await security_service.record_login_attempt(
                    db, user, False, ip_address, user_agent
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not belong to the specified clinic",
                )

            # Create session and tokens
            tokens = await self._create_login_tokens(db, user)

            # Record successful login
            await security_service.record_login_attempt(
                db, user, True, ip_address, user_agent
            )

            # Update login analytics
            await self._update_login_analytics(db, user, tenant)

            logger.info(
                f"Successful login for user: {user.email} from IP: {ip_address}"
            )

            return {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": "bearer",
                "user": user,
                "tenant_status": tenant.status if tenant else None,
                "tenant_tier": tenant.tier if tenant else None,
                "session_id": tokens["session_id"],
                "password_reset_required": self._should_force_password_reset(user),
            }

        except HTTPException:
            # Record failed attempt for security exceptions
            if "user" in locals() and "ip_address" in locals():
                await security_service.record_login_attempt(
                    db, user, False, ip_address, user_agent
                )
            raise
        except Exception as e:
            logger.error(f"Unexpected login error for {login_data.email}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login failed due to a server error. Please try again.",
            )

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
        """Check if password reset should be forced"""
        # First login
        if user.last_login_at is None:
            return True

        # Password expired
        if password_policy_service.is_password_expired(user):
            return True

        # Admin forced reset
        if user.settings.get("force_password_reset"):
            return True

        # Security policy requires reset
        if user.settings.get("password_reset_required"):
            return True

        return False

    async def _update_login_analytics(
        self, db: AsyncSession, user: User, tenant: Optional[Tenant]
    ):
        """Update login analytics for business intelligence"""
        try:
            # Update user's login count and last login
            user.login_count = (user.login_count or 0) + 1
            user.last_login_at = datetime.utcnow()

            # Update tenant analytics if available
            if tenant:
                # TODO: Update tenant-level login analytics
                # This could include peak usage times, user engagement, etc.
                pass

            await db.commit()

        except Exception as e:
            logger.error(f"Error updating login analytics: {e}")
            # Don't fail the login if analytics update fails

    async def _create_login_tokens(
        self, db: AsyncSession, user: User
    ) -> Dict[str, str]:
        """Create secure login tokens with session management"""
        # Generate session ID
        session_id = uuid4()

        # Create access token with enhanced claims
        access_token = self.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
                "session_id": str(session_id),
                "login_time": datetime.utcnow().isoformat(),
                "auth_method": "password",
            }
        )

        # Create and store refresh token with session context
        refresh_token, token_id = self.create_refresh_token(user.id)
        expires_at = datetime.utcnow() + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Store refresh token with session info
        await self.store_refresh_token(
            db, token_id, getattr(user, "id"), expires_at, session_id
        )

        # Update user's last login
        user.last_login_at = datetime.utcnow()
        await db.commit()

        # Eager load relationships
        await db.refresh(user, ["tenant"])

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "session_id": str(session_id),
        }

    async def create_tenant_admin_user(
        self, db: AsyncSession, tenant: Tenant, email: str
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
                is_active=True,
            )

            user = await self.create_user(db, user_data, tenant.id)

            logger.info(
                f"Created tenant admin user: {email} for tenant: {tenant.name} with password: {temp_password}"
            )

            # Send welcome email with setup instructions
            await email_service.send_tenant_welcome_email(
                user_email=user.email,
                user_name=f"{user.first_name} {user.last_name}",
                temp_password=temp_password,
                tenant_slug=tenant.slug,
            )

            return user

        except Exception as e:
            logger.error(f"Failed to create tenant admin user: {e}")
            raise

    async def refresh_tokens(
        self, db: AsyncSession, refresh_token: str
    ) -> Dict[str, Any]:
        """Refresh access token using refresh token"""
        user = await self.verify_refresh_token(db, refresh_token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
            )

        # Create new access token
        access_token = self.create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role}
        )

        # Optionally rotate refresh token (for better security)
        if settings.REFRESH_TOKEN_ROTATION:
            # Revoke old token
            payload = jwt.decode(
                refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            old_token_id = UUID(payload.get("jti"))
            await self.revoke_refresh_token(db, old_token_id)

            # Create new refresh token
            new_refresh_token, new_token_id = self.create_refresh_token(user.id)
            expires_at = datetime.utcnow() + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
            await self.store_refresh_token(db, new_token_id, user.id, expires_at)

            return {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
            }
        else:
            return {"access_token": access_token, "token_type": "bearer"}

    async def logout(self, db: AsyncSession, refresh_token: str) -> None:
        """Logout user by revoking refresh token"""
        try:
            payload = jwt.decode(
                refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            token_id = UUID(payload.get("jti"))
            await self.revoke_refresh_token(db, token_id)
        except JWTError:
            # Token is invalid anyway, so consider it logged out
            pass

    async def logout_all(self, db: AsyncSession, user_id: UUID) -> None:
        """Logout user from all devices"""
        await self.revoke_all_user_tokens(db, user_id)

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
            )

            if payload.get("type") != "access":
                raise credentials_exception

            user_id: str = payload.get("sub")
            if user_id is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        user = await self.user_service.get(db, UUID(user_id))
        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
            )

        return user

    async def create_user(
        self, db: AsyncSession, user_data: UserCreate, tenant_id: UUID = None
    ) -> User:
        """Create user - automatically uses current tenant context if not specified"""
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

        # Set tenant context
        if tenant_id:
            user_data_dict["tenant_id"] = tenant_id

        # Initialize user settings with security defaults
        user_data_dict["settings"] = {
            "password_changed_at": datetime.utcnow().isoformat(),
            "login_count": 0,
            "account_locked_until": None,
            "force_password_reset": user_data_dict.get("last_login_at")
            is None,  # Force reset on first login
        }

        user = User(**user_data_dict)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"Created new user: {user.email} in tenant: {user.tenant_id}")

        # TODO: Send welcome email with security guidelines
        # TODO: Log user creation for audit purposes
        return user


auth_service = AuthService()
