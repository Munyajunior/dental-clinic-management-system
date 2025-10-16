# src/routes/auth.py (Enhanced)
from fastapi import APIRouter, Depends, status, HTTPException, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from db.database import get_db
from schemas.user_schemas import (
    UserLogin,
    UserLoginResponse,
    UserCreate,
    UserPublic,
)
from schemas.auth_schemas import TokenResponse
from schemas.auth_schemas import RefreshTokenRequest, LogoutRequest, LogoutResponse
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("AUTH_ROUTER")

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/login",
    response_model=UserLoginResponse,
    summary="User login",
    description="Authenticate user and return access and refresh tokens",
)
@limiter.limit("5/minute")
async def login(
    request: Request, login_data: UserLogin, db: AsyncSession = Depends(get_db)
) -> Any:
    """User login endpoint"""
    result = await auth_service.login(db, login_data)
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "user": UserPublic.from_orm(result["user"]),
    }


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh tokens",
    description="Refresh access token using refresh token. Implements token rotation for security.",
)
async def refresh_tokens(
    refresh_data: RefreshTokenRequest = Body(...), db: AsyncSession = Depends(get_db)
) -> Any:
    """Refresh tokens endpoint with secure token rotation"""
    try:
        result = await auth_service.refresh_tokens(db, refresh_data.refresh_token)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not refresh tokens"
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="User logout",
    description="Logout user by revoking refresh token",
)
async def logout(
    logout_data: LogoutRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """User logout endpoint"""
    await auth_service.logout(db, logout_data.refresh_token)
    return LogoutResponse(message="Successfully logged out")


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
    summary="Logout all devices",
    description="Logout user from all devices by revoking all refresh tokens",
)
async def logout_all(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """Logout from all devices endpoint"""
    await auth_service.logout_all(db, current_user.id)
    return LogoutResponse(message="Successfully logged out from all devices")


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account",
)
@limiter.limit("10/minute")
async def register(
    request: Request, user_data: UserCreate, db: AsyncSession = Depends(get_db)
) -> Any:
    """User registration endpoint"""
    user = await auth_service.create_user(db, user_data)
    return UserPublic.from_orm(user)


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get current user",
    description="Get current authenticated user information",
)
async def get_current_user(
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get current user endpoint"""
    return UserPublic.from_orm(current_user)
