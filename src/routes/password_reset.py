# src/routes/password_reset.py
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
    BackgroundTasks,
    Body,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, func
from typing import Any
from uuid import UUID
from datetime import datetime, timedelta, timezone
from db.database import get_db, get_db_session
from schemas.password_reset_schemas import (
    PasswordResetRequest,
    PasswordResetVerify,
    PasswordResetComplete,
    PasswordResetResponse,
    EnforcedPasswordReset,
    ChangePasswordRequest,
)
from schemas.user_schemas import UserPublic
from models.user import StaffRole, User
from services.password_reset_service import password_reset_service
from services.auth_service import auth_service
from core.config import settings
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
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Request password reset endpoint"""
    try:
        result = await password_reset_service.request_password_reset(
            db, reset_request.email, background_tasks
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
    complete_request: PasswordResetComplete,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Complete password reset endpoint"""
    try:
        result = await password_reset_service.complete_password_reset(
            db, complete_request.token, complete_request.new_password, background_tasks
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


@router.post(
    "{user_id}/enforced-password-reset",
    response_model=PasswordResetResponse,
    summary="Enforced password reset",
    description="Reset password for enforced scenarios (first login, admin requirement)",
)
async def enforced_password_reset(
    request: Request,
    user_id: UUID,
    reset_data: EnforcedPasswordReset = Body(...),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Enforced password reset endpoint"""
    try:
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        # Get user by ID
        user = await auth_service.user_service.get(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Verify email matches user ID (additional security)
        if user.email != reset_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match user account",
            )

        # Check if user is allowed to do enforced reset
        if not auth_service.can_user_do_enforced_reset(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Enforced password reset not allowed",
            )

        # Update password
        await auth_service.update_user_password(db, user_id, reset_data.new_password)

        # Clear any password reset flags
        await auth_service.clear_password_reset_requirements(db, user_id)

        session_id, session_data = (
            await auth_service.session_service.create_user_session(
                db, user.id, client_ip, user_agent
            )
        )

        # Create new tokens since this is essentially a new login
        access_token = auth_service.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
            },
            session_id=session_id,
        )

        refresh_token, token_id = auth_service.create_refresh_token(
            str(user.id), session_id
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        await auth_service.store_refresh_token(
            db, token_id, str(user.id), expires_at, session_id
        )

        return PasswordResetResponse(
            success=True,
            message="Password reset successfully",
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserPublic.from_orm(user),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enforced password reset failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password",
        )


@router.post(
    "/enforced-password-reset",
    response_model=PasswordResetResponse,
    summary="Enforced password reset",
    description="Reset password for enforced scenarios (first login, admin requirement)",
)
async def enforced_password_reset_by_slug(
    request: Request,
    reset_data: EnforcedPasswordReset = Body(...),
    db: AsyncSession = Depends(get_db_session),  # Use system session
) -> Any:
    """Enforced password reset endpoint that doesn't require tenant context"""
    try:
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        logger.info(
            f"Enforced password reset attempt for: {reset_data.email} in tenant: {reset_data.tenant_slug}"
        )

        # Get user by email and tenant slug
        user = await auth_service.get_user_by_email_and_tenant(
            db, reset_data.email, reset_data.tenant_slug
        )
        if not user:
            logger.warning(
                f"User not found: {reset_data.email} in tenant: {reset_data.tenant_slug}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in specified clinic. Please check your email and clinic name.",
            )

        logger.info(
            f"Found user: {user.email} (ID: {user.id}), reset flags: {user.settings}"
        )

        # Verify this is an allowed enforced reset scenario
        if not auth_service.can_user_do_enforced_reset(user):
            logger.warning(
                f"Enforced reset not allowed for user: {user.email}, settings: {user.settings}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password reset not allowed for this user. Please contact your administrator.",
            )

        # Update password - with explicit commit
        logger.info(f"Updating password for user: {user.email}")
        updated_user = await auth_service.update_user_password(
            db, getattr(user, "id"), reset_data.new_password, revoke_other_sessions=True
        )

        # Clear any password reset flags - with multiple attempts if needed
        logger.info(
            f"Clearing password reset requirements for user: {user.email}, current settings: {user.settings}"
        )

        # First attempt
        await auth_service.clear_password_reset_requirements(db, getattr(user, "id"))

        # Verify immediately
        await db.refresh(updated_user)
        logger.info(f"After first clear - user settings: {updated_user.settings}")

        # If still not cleared, try again
        if updated_user.settings.get("force_password_reset"):
            logger.warning("Reset flag still present, attempting second clear")
            await auth_service.clear_password_reset_requirements(
                db, getattr(user, "id")
            )
            await db.refresh(updated_user)
            logger.info(f"After second clear - user settings: {updated_user.settings}")

        # Final verification
        requirements_cleared = (
            await auth_service.verify_password_reset_requirements_cleared(
                db, getattr(user, "id")
            )
        )
        if not requirements_cleared:
            logger.error(
                f"Password reset requirements STILL not cleared for user: {user.email}"
            )
            # Force clear by direct update
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    settings=func.jsonb_set(
                        User.settings, "{force_password_reset}", "false", True
                    )
                )
            )
            await db.commit()
            await db.refresh(updated_user)
            logger.info(f"After forced clear - user settings: {updated_user.settings}")

        # Create session and tokens
        session_id, session_data = (
            await auth_service.session_service.create_user_session(
                db, getattr(user, "id"), client_ip, user_agent
            )
        )

        # Create new token pair with session ID
        # Note: We're using the user's email as the subject to match the login flow
        # This is safe since this is essentially a new login
        access_token = auth_service.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "tenant_id": str(user.tenant_id),
            },
            session_id=session_id,
        )

        refresh_token, token_id = auth_service.create_refresh_token(
            str(user.id), session_id
        )
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        await auth_service.store_refresh_token(
            db, token_id, str(user.id), expires_at, session_id
        )

        # Convert user to UserPublic safely
        user_public = UserPublic(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            contact_number=user.contact_number,
            role=user.role,
            specialization=user.specialization,
            is_active=user.is_active,
            is_available=user.is_available,
            profile_picture=(
                user.get_profile_picture_base64()
                if hasattr(user, "get_profile_picture_base64")
                else None
            ),
        )

        logger.info(
            f"Enforced password reset completed successfully for user: {user.email}"
        )

        return PasswordResetResponse(
            success=True,
            message="Password reset successfully. You can now access your account.",
            access_token=access_token,
            refresh_token=refresh_token,
            user=user_public,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enforced password reset failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while resetting your password. Please try again.",
        )


@router.post(
    "/{user_id}/change-password",
    response_model=PasswordResetResponse,
    summary="Change password",
    description="Change user password",
)
async def change_password(
    user_id: UUID,
    password_data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Change password endpoint"""
    try:
        # Users can change their own password, admins can change any
        if current_user.id != user_id and current_user.role not in ["admin", "manager"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to change this user's password",
            )

        # Verify current password
        if not await auth_service.verify_current_password(
            db, current_user.id, password_data.current_password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

        # Update password
        await auth_service.update_user_password(
            db, current_user.id, password_data.new_password
        )

        logger.info(f"Password changed voluntarily for user: {current_user.email}")

        return PasswordResetResponse(
            success=True, message="Password changed successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password change failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password",
        )


@router.post(
    "/{user_id}/force-password-reset",
    response_model=PasswordResetResponse,
    summary="Admin force password reset",
    description="Admin endpoint to force a password reset for a user",
)
async def admin_force_password_reset(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Admin endpoint to force password reset for a user"""
    try:
        # Check if current user has admin privileges
        if current_user.role not in [StaffRole.ADMIN, StaffRole.MANAGER]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

        # Get target user
        target_user = await auth_service.user_service.get(db, user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Verify same tenant (security)
        if target_user.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify users from other tenants",
            )

        # Set force password reset flag
        target_user.settings["force_password_reset"] = True
        target_user.settings["force_reset_reason"] = (
            f"Admin forced by {current_user.email}"
        )
        target_user.settings["force_reset_at"] = datetime.utcnow().isoformat()

        await db.commit()

        logger.info(
            f"Admin {current_user.email} forced password reset for user: {target_user.email}"
        )

        return PasswordResetResponse(
            success=True, message="Password reset has been forced for the user"
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Admin force password reset failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to force password reset",
        )
