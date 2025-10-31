# src/routes/auth.py (Enhanced)
from fastapi import APIRouter, Depends, status, HTTPException, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from db.database import get_db, get_db_session
from schemas.user_schemas import (
    UserLogin,
    UserLoginResponse,
    UserCreate,
    UserPublic,
)
from schemas.auth_schemas import (
    RefreshTokenRequest,
    LogoutRequest,
    LogoutResponse,
    TokenRefreshResponse,
)
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
    request: Request, login_data: UserLogin, db: AsyncSession = Depends(get_db_session)
) -> Any:
    """User login endpoint - uses system session to find user across tenants"""
    try:
        # Get client IP and user agent for security
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        result = await auth_service.login(
            db, login_data, ip_address=client_ip, user_agent=user_agent, request=request
        )

        return UserLoginResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            token_type=result["token_type"],
            user=UserPublic.from_orm(result["user"]),
            tenant=result.get("tenant"),
            session_id=result["session_id"],
            password_reset_required=result.get("password_reset_required", False),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed due to a server error",
        )


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    summary="Refresh tokens",
    description="Refresh access token using refresh token. Implements token rotation for security.",
)
async def refresh_tokens(
    refresh_data: RefreshTokenRequest = Body(...),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Refresh tokens endpoint with secure token rotation"""
    try:
        result = await auth_service.refresh_tokens(db, refresh_data.refresh_token)

        response_data = {
            "access_token": result["access_token"],
            "token_type": result["token_type"],
            "session_id": result.get("session_id"),
        }

        # Include refresh_token only if provided (token rotation)
        if "refresh_token" in result:
            response_data["refresh_token"] = result["refresh_token"]

        return TokenRefreshResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not refresh tokens"
        )


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account within current tenant",
)
@limiter.limit("10/minute")
async def register(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),  # TENANT session - requires tenant context
) -> Any:
    """User registration endpoint - creates user within current tenant"""
    user = await auth_service.create_user(db, user_data)
    await db.commit()
    return UserPublic.from_orm(user)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="User logout",
    description="Logout user by revoking refresh token and session",
)
async def logout(
    logout_data: LogoutRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """User logout endpoint"""
    try:
        user, session_id = current_user  # Unpack tuple from get_current_user
        result = await auth_service.logout(
            db=db,
            refresh_token=logout_data.refresh_token,
            session_id=session_id,
            user_id=user.id,
        )

        return LogoutResponse(
            success=True,
            message="Successfully logged out",
            sessions_revoked=result.get("sessions_revoked", 0),
            tokens_revoked=result.get("tokens_revoked", 0),
        )

    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed"
        )


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
    summary="Logout all devices",
    description="Logout user from all devices by revoking all refresh tokens and sessions",
)
async def logout_all(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """Logout from all devices endpoint"""
    try:
        user, _ = current_user  # Unpack tuple, ignore session_id for logout-all
        result = await auth_service.logout_all(db, user.id)

        return LogoutResponse(
            success=True,
            message=result.get("message", "Successfully logged out from all devices"),
            sessions_revoked=result.get("sessions_revoked", 0),
            tokens_revoked=result.get("tokens_revoked", 0),
        )

    except Exception as e:
        logger.error(f"Logout all error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to logout from all devices",
        )


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get current user",
    description="Get current authenticated user information",
)
async def get_current_user(
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get current user endpoint - requires tenant context"""
    try:
        user, _ = current_user
        return UserPublic.from_orm(user)
    except Exception as e:
        logger.error(f"Get current user error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve user information",
        )
