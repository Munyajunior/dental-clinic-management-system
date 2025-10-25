# src/routes/password_reset.py
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from pydantic import EmailStr
from db.database import get_db
from schemas.password_reset_schemas import (
    PasswordResetRequest,
    PasswordResetVerify,
    PasswordResetComplete,
    PasswordResetResponse,
)
from services.password_reset_service import password_reset_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("PASSWORD_RESET_ROUTES")

router = APIRouter(prefix="/password-reset", tags=["password-reset"])


@router.post(
    "/request",
    response_model=PasswordResetResponse,
    summary="Request password reset",
    description="Request a password reset link for a user",
)
@limiter.limit("5/minute")
async def request_password_reset(
    request: Request,
    reset_request: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Request password reset endpoint"""
    try:
        result = await password_reset_service.request_password_reset(
            db, reset_request.email
        )

        if result["success"]:
            logger.info(f"Password reset requested for: {reset_request.email}")
            return PasswordResetResponse(
                success=True,
                message="If an account with that email exists, a reset link has been sent.",
            )
        else:
            # Don't reveal if email exists or not for security
            return PasswordResetResponse(
                success=True,
                message="If an account with that email exists, a reset link has been sent.",
            )

    except Exception as e:
        logger.error(f"Password reset request failed: {e}")
        return PasswordResetResponse(
            success=True,  # Always return success for security
            message="If an account with that email exists, a reset link has been sent.",
        )


@router.post(
    "/verify",
    response_model=PasswordResetResponse,
    summary="Verify reset token",
    description="Verify if a password reset token is valid",
)
async def verify_reset_token(
    verify_request: PasswordResetVerify, db: AsyncSession = Depends(get_db)
) -> Any:
    """Verify reset token endpoint"""
    try:
        is_valid = await password_reset_service.verify_reset_token(
            db, verify_request.token
        )

        if is_valid:
            return PasswordResetResponse(success=True, message="Token is valid")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )

    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )


@router.post(
    "/complete",
    response_model=PasswordResetResponse,
    summary="Complete password reset",
    description="Complete password reset with new password",
)
async def complete_password_reset(
    complete_request: PasswordResetComplete, db: AsyncSession = Depends(get_db)
) -> Any:
    """Complete password reset endpoint"""
    try:
        result = await password_reset_service.complete_password_reset(
            db, complete_request.token, complete_request.new_password
        )

        if result["success"]:
            logger.info(f"Password reset completed for user: {result.get('user_id')}")
            return PasswordResetResponse(
                success=True, message="Password has been reset successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to reset password"),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset completion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to reset password"
        )
