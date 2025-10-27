# src/services/auth_service.py (Enhanced)
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from sqlalchemy import select, delete, and_
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import settings
from models.user import StaffRole, GenderEnum
from models.user import User
from models.tenant import Tenant, TenantStatus, TenantTier
from models.auth import RefreshToken
from schemas.user_schemas import UserLogin, UserCreate
from services.email_service import email_service
from utils.logger import setup_logger
from .base_service import BaseService
import secrets
import string

logger = setup_logger("AUTH_SERVICE")

security = HTTPBearer()
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class TenantStatusService:
    """Service for handling tenant status and subscription logic"""

    @staticmethod
    def can_tenant_accept_logins(tenant: Tenant) -> Tuple[bool, str]:
        """
        Check if tenant can accept logins with detailed status analysis
        Returns: (can_login: bool, message: str)
        """
        current_time = datetime.utcnow()

        # Check tenant status
        if tenant.status == TenantStatus.CANCELLED:
            return (
                False,
                "This clinic account has been cancelled. Please contact support.",
            )

        elif tenant.status == TenantStatus.SUSPENDED:
            return (
                False,
                "This clinic account has been suspended. Please contact support to reactivate.",
            )

        elif tenant.status == TenantStatus.TRIAL:
            # Check trial expiration
            if tenant.trial_ends_at and tenant.trial_ends_at < current_time:
                return (
                    False,
                    "Your trial period has ended. Please upgrade to continue using our services.",
                )

            # Check if trial has usage limits exceeded
            if not TenantStatusService._check_trial_limits(tenant):
                return False, "Trial usage limits exceeded. Please upgrade to continue."

            return True, "Trial account active"

        elif tenant.status == TenantStatus.ACTIVE:
            # Check subscription expiration for paid plans
            if tenant.tier != TenantTier.TRIAL and tenant.subscription_ends_at:
                if tenant.subscription_ends_at < current_time:
                    return (
                        False,
                        "Your subscription has expired. Please renew to continue using our services.",
                    )

            # Check for active subscription issues
            if not TenantStatusService._check_subscription_status(tenant):
                return (
                    False,
                    "There's an issue with your subscription. Please contact support.",
                )

            return True, "Active account"

        else:
            return False, "Unknown account status. Please contact support."

    @staticmethod
    def _check_trial_limits(tenant: Tenant) -> bool:
        """Check if trial account has exceeded any limits"""
        # Implement trial limit checks
        # Example: Check user count, patient count, storage, etc.
        # This would require additional queries to count current usage
        return True  # Placeholder

    @staticmethod
    def _check_subscription_status(tenant: Tenant) -> bool:
        """Check subscription status for paid plans"""
        # Implement subscription validation
        # Check with payment processor, check for failed payments, etc.
        return True  # Placeholder

    @staticmethod
    def get_tenant_tier_features(tier: TenantTier) -> Dict[str, Any]:
        """Get features and limits for each tier"""
        tier_features = {
            TenantTier.TRIAL: {
                "max_users": 5,
                "max_patients": 100,
                "max_storage_gb": 1,
                "features": ["basic_appointments", "patient_management"],
                "support_level": "email_only",
                "trial_days": 30,
            },
            TenantTier.BASIC: {
                "max_users": 10,
                "max_patients": 1000,
                "max_storage_gb": 10,
                "features": [
                    "basic_appointments",
                    "patient_management",
                    "basic_reporting",
                ],
                "support_level": "business_hours",
            },
            TenantTier.PROFESSIONAL: {
                "max_users": 25,
                "max_patients": 5000,
                "max_storage_gb": 50,
                "features": [
                    "advanced_appointments",
                    "patient_management",
                    "advanced_reporting",
                    "api_access",
                ],
                "support_level": "priority",
            },
            TenantTier.ENTERPRISE: {
                "max_users": 100,
                "max_patients": "unlimited",
                "max_storage_gb": 100,
                "features": [
                    "all_features",
                    "custom_integrations",
                    "dedicated_support",
                ],
                "support_level": "dedicated",
            },
        }
        return tier_features.get(tier, {})


class AuthService:
    def __init__(self):
        self.user_service = BaseService(User)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def generate_pronounceable_password(self, length: int = 10) -> str:
        """
        Generate a more user-friendly but still secure password
        """
        vowels = "aeiou"
        consonants = "bcdfghjklmnpqrstvwxyz"

        password = []
        for i in range(length):
            if i % 2 == 0:
                password.append(secrets.choice(consonants))
            else:
                password.append(secrets.choice(vowels))

        # Add a digit and special character
        password.append(secrets.choice(string.digits))
        password.append(secrets.choice("!@#$%"))

        secrets.SystemRandom().shuffle(password)
        return "".join(password)

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
        self, db: AsyncSession, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        """Store refresh token in database"""
        refresh_token = RefreshToken(
            id=token_id, user_id=user_id, expires_at=expires_at, is_revoked=False
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

    async def login(self, db: AsyncSession, login_data: UserLogin) -> Dict[str, Any]:
        """
        Enhanced login with comprehensive tenant status checking
        """
        try:
            # Validate required fields
            if not login_data.email or not login_data.password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email and password are required",
                )

            # Tenant lookup and validation
            tenant = await self._validate_tenant_for_login(db, login_data.tenant_slug)

            # User authentication
            user = await self._authenticate_user_for_login(
                db, login_data.email, login_data.password, tenant
            )

            # Check tenant status and subscription
            await self._check_tenant_login_eligibility(tenant)

            # Check user status
            await self._check_user_login_eligibility(user)

            # Verify tenant-user relationship
            if tenant and user.tenant_id != tenant.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not belong to the specified clinic",
                )

            # Create tokens and update last login
            tokens = await self._create_login_tokens(db, user)

            logger.info(
                f"Successful login for user: {user.email} in tenant: {tenant.slug if tenant else user.tenant_id}"
            )

            return {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": "bearer",
                "user": user,
                "tenant_status": tenant.status if tenant else None,
                "tenant_tier": tenant.tier if tenant else None,
            }

        except HTTPException:
            # Re-raise known HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected login error for {login_data.email}: {str(e)}")
            # Don't expose internal errors to users
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Login failed due to a server error. Please try again.",
            )

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
                User.is_active == True,  # Only active users can login
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

    async def _check_tenant_login_eligibility(self, tenant: Optional[Tenant]) -> None:
        """Check if tenant is eligible for login"""
        if not tenant:
            return  # No tenant specified, skip tenant checks

        can_login, message = self.tenant_status_service.can_tenant_accept_logins(tenant)

        if not can_login:
            # Map to appropriate HTTP status codes based on the reason
            if "cancelled" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,  # Gone - resource no longer available
                    detail=message,
                )
            elif "suspended" in message.lower() or "trial ended" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,  # Forbidden - account issue
                    detail=message,
                )
            elif "limits exceeded" in message.lower():
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,  # Payment required
                    detail=message,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=message
                )

    async def _check_user_login_eligibility(self, user: User) -> None:
        """Check if user is eligible for login"""
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has been deactivated. Please contact your clinic administrator.",
            )

        # Check if user needs to reset password (first login, password expired, etc.)
        if self._should_force_password_reset(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password reset required. Please use the 'Forgot Password' feature.",
            )

    def _should_force_password_reset(self, user: User) -> bool:
        """Check if user should be forced to reset password"""
        # Implement logic for forced password resets
        # - First login (never logged in before)
        # - Password expired (based on policy)
        # - Admin forced reset
        return user.last_login_at is None  # Force reset on first login

    async def _create_login_tokens(
        self, db: AsyncSession, user: User
    ) -> Dict[str, str]:
        """Create access and refresh tokens for successful login"""
        # Create access token with tenant context
        access_token = self.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
                "login_time": datetime.utcnow().isoformat(),
            }
        )

        # Create and store refresh token
        refresh_token, token_id = self.create_refresh_token(user.id)
        expires_at = datetime.utcnow() + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        await self.store_refresh_token(db, token_id, user.id, expires_at)

        # Update last login timestamp
        user.last_login_at = datetime.utcnow()
        await db.commit()

        # Eager load tenant relationship for response
        await db.refresh(user, ["tenant"])

        return {"access_token": access_token, "refresh_token": refresh_token}

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

        # If tenant_id is not provided, the RLS will automatically use the current tenant context
        # from the database session (set by the middleware)
        if tenant_id:
            user_data_dict["tenant_id"] = tenant_id
        # If tenant_id is not provided, the user will be created in the current tenant context
        # This is the case when registering users within a tenant

        user = User(**user_data_dict)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"Created new user: {user.email} in tenant: {user.tenant_id}")
        return user


auth_service = AuthService()
