# src/routes/sessions.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from db.database import get_db
from schemas.auth_schemas import (
    ActiveSessionsResponse,
    SessionInfo,
    ForceLogoutRequest,
    LogoutResponse,
)
from services.auth_service import auth_service
from utils.logger import setup_logger

logger = setup_logger("SESSION_ROUTER")

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get(
    "/my-sessions",
    response_model=ActiveSessionsResponse,
    summary="Get my active sessions",
    description="Get all active sessions for the current user",
)
async def get_my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(auth_service.get_current_user),
) -> ActiveSessionsResponse:
    """Get current user's active sessions"""
    try:
        user, current_session_id = current_user

        sessions = await auth_service.session_service.get_active_sessions(db, user.id)

        return ActiveSessionsResponse(
            success=True, sessions=sessions, total_sessions=len(sessions)
        )

    except Exception as e:
        logger.error(f"Error getting user sessions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        )


@router.post(
    "/{session_id}/revoke",
    response_model=LogoutResponse,
    summary="Revoke specific session",
    description="Revoke a specific session by ID",
)
async def revoke_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """Revoke a specific session"""
    try:
        user, current_session_id = current_user

        # Users can only revoke their own sessions
        if session_id == current_session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot revoke current session. Use logout instead.",
            )

        success = await auth_service.session_service.revoke_session(
            db, session_id, user.id, "user_revoked"
        )

        if success:
            return LogoutResponse(
                success=True,
                message="Session revoked successfully",
                sessions_revoked=1,
                tokens_revoked=0,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already revoked",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke session",
        )


@router.post(
    "/revoke-others",
    response_model=LogoutResponse,
    summary="Revoke other sessions",
    description="Revoke all other sessions except the current one",
)
async def revoke_other_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """Revoke all sessions except current one"""
    try:
        user, current_session_id = current_user

        revoked_count = await auth_service.session_service.revoke_all_user_sessions(
            db,
            user.id,
            exclude_session_id=current_session_id,
            reason="user_revoked_others",
        )

        return LogoutResponse(
            success=True,
            message=f"Revoked {revoked_count} other sessions",
            sessions_revoked=revoked_count,
            tokens_revoked=0,
        )

    except Exception as e:
        logger.error(f"Error revoking other sessions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke other sessions",
        )


# Admin endpoints for session management
@router.get(
    "/user/{user_id}/sessions",
    response_model=ActiveSessionsResponse,
    summary="Get user sessions (Admin)",
    description="Get all active sessions for a user (Admin only)",
)
async def get_user_sessions_admin(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(auth_service.get_current_user),
) -> ActiveSessionsResponse:
    """Admin endpoint to get user sessions"""
    try:
        admin_user, _ = current_user

        # Check if user has admin privileges
        if admin_user.role not in ["admin", "manager"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

        sessions = await auth_service.session_service.get_active_sessions(db, user_id)

        return ActiveSessionsResponse(
            success=True, sessions=sessions, total_sessions=len(sessions)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin error getting user sessions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user sessions",
        )


@router.post(
    "/admin/force-logout",
    response_model=LogoutResponse,
    summary="Force user logout (Admin)",
    description="Force logout a user from all devices (Admin only)",
)
async def admin_force_logout(
    request: ForceLogoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: tuple = Depends(auth_service.get_current_user),
) -> LogoutResponse:
    """Admin endpoint to force user logout"""
    try:
        admin_user, _ = current_user

        # Check if user has admin privileges
        if admin_user.role not in ["admin", "manager"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

        # Verify same tenant (security)
        target_user = await auth_service.user_service.get(db, request.user_id)
        if not target_user or target_user.tenant_id != admin_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in your tenant",
            )

        result = await auth_service.logout_all(db, request.user_id)

        return LogoutResponse(
            success=True,
            message=f"Force logged out user {target_user.email}",
            sessions_revoked=result.get("sessions_revoked", 0),
            tokens_revoked=result.get("tokens_revoked", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin force logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to force logout user",
        )
