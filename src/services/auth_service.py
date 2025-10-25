# src/services/auth_service.py (Enhanced)
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db
from sqlalchemy import select, delete
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import settings
from models.user import User
from models.tenant import Tenant
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
        self, db: AsyncSession, email: str, password: str
    ) -> Optional[User]:
        try:
            result = await db.execute(
                select(User).where(User.email == email, User.is_active)
            )
            user = result.scalar_one_or_none()

            if user and self.verify_password(password, user.hashed_password):
                return user
            return None
        except Exception as e:
            logger.error(f"Authentication error for {email}: {e}")
            return None

    async def login(self, db: AsyncSession, login_data: UserLogin) -> Dict[str, Any]:
        user = await self.authenticate_user(db, login_data.email, login_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
            )

        # Create tokens
        access_token = self.create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role}
        )

        refresh_token, token_id = self.create_refresh_token(user.id)
        expires_at = datetime.utcnow() + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Store refresh token
        await self.store_refresh_token(db, token_id, user.id, expires_at)

        # Update last login
        user.last_login_at = datetime.utcnow()
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": user,
        }

    async def create_tenant_admin_user(
        self, db: AsyncSession, tenant: Tenant, email: str
    ) -> User:
        """Create default admin user for new tenant"""
        from schemas.user_schemas import UserCreate
        from models.user import StaffRole, GenderEnum

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

            user = await self.create_user(db, user_data)

            logger.info(f"Created tenant admin user: {email} for tenant: {tenant.name}")

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

    async def create_user(self, db: AsyncSession, user_data: UserCreate) -> User:
        result = await db.execute(select(User).where(User.email == user_data.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists",
            )

        hashed_password = self.get_password_hash(user_data.password)
        user_data_dict = user_data.dict(exclude={"password"})
        user_data_dict["hashed_password"] = hashed_password

        user = User(**user_data_dict)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"Created new user: {user.email}")
        return user


auth_service = AuthService()
