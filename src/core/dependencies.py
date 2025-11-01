from datetime import datetime, timezone
from typing import Union
from db.database import get_db
from core.config import settings
from fastapi import Depends, HTTPException, status, Header
from jose import JWTError, jwt
from models.patient import Patient
from models.user import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.exceptions import (
    ForbiddenException,
    UnauthorizedException,
    NotFoundException,
)
from utils.logger import setup_logger

logger = setup_logger("ROLE CHECKER")


async def get_current_user(
    authorization: str = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Union[User, Patient]:
    """
    Dependency to get current authenticated user from JWT token

    Args:
        authorization: Bearer token from Authorization header
        db: Async database session

    Returns:
        Authenticated User or Patient object

    Raises:
        HTTPException: 401 if authentication fails
    """
    if not authorization:
        logger.warning("Authorization header missing")
        raise UnauthorizedException("Authorization header is missing")

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            logger.warning(f"Invalid auth scheme: {scheme}")
            raise UnauthorizedException("Invalid authentication scheme")

        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # Check token expiration
        exp = payload.get("exp")
        if exp is not None:
            current_time = datetime.now(timezone.utc)
            expiry_time = datetime.fromtimestamp(exp, timezone.utc)
            if current_time > expiry_time:
                logger.warning(f"Token expired at {expiry_time}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        user_id = payload.get("sub")
        role = payload.get("role")

        logger.debug(f"Authenticating user with ID: {user_id}")

        if not user_id or not role:
            logger.warning("Invalid token payload - missing sub or role")
            raise UnauthorizedException("Invalid token payload")

        # Get user from appropriate table based on role
        if role == "patient":
            result = await db.execute(select(Patient).where(Patient.id == user_id))
            user = result.scalar_one_or_none()
        else:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"User not found in database: {user_id}")
            raise NotFoundException("User not found")

        logger.info(f"Authenticated user: {user_id} ({role})")
        return user

    except (JWTError, ValueError) as e:
        logger.error(f"JWT validation failed: {str(e)}")
        raise UnauthorizedException("Could not validate credentials")


async def get_current_active_user(
    current_user: Union[User, Patient] = Depends(get_current_user),
) -> Union[User, Patient]:
    """
    Dependency to verify the current user is active

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        Active user if verification passes

    Raises:
        HTTPException: 400 if user is inactive
    """
    if isinstance(current_user, Patient):
        return current_user

    if not getattr(current_user, "is_active"):
        logger.warning(f"Inactive user attempted access: {current_user.id}")
        raise ForbiddenException("Inactive user")
    return current_user


class RoleChecker:
    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    async def __call__(
        self, user: Union[User, Patient] = Depends(get_current_active_user)
    ) -> Union[User, Patient]:
        """
        Dependency to verify user has required role

        Args:
            user: Authenticated and active user from get_current_active_user

        Returns:
            User if role check passes

        Raises:
            HTTPException: 403 if role check fails
        """
        if not hasattr(user, "role") or user.role not in self.allowed_roles:
            logger.warning(
                f"Role check failed for {user.id}. "
                f"Required: {self.allowed_roles}, Has: {getattr(user, 'role', None)}"
            )
            raise ForbiddenException("Operation not permitted")
        return user
