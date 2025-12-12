# src/services/password_reset_service.py
from core.email_config import email_settings
from fastapi import BackgroundTasks, HTTPException, Request
import asyncio
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from db.database import AsyncSessionLocal
from models.user import User
from models.auth import PasswordResetToken
from services.email_service import email_service
from services.auth_service import auth_service
from utils.url_scheme_handler import URLSchemeHandler
from schemas.email_schemas import EmailType
from utils.logger import setup_logger

logger = setup_logger("PASSWORD_RESET_SERVICE")


class PasswordResetService:
    """Service for handling password reset operations"""

    def __init__(self):
        self.token_expiry_hours = 1  # Token expires after 1 hour

    async def request_password_reset(
        self,
        request: Request,
        db: AsyncSession,
        user_id: UUID,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        """Request password reset for a user"""
        try:
            # Find user by id
            result = await db.execute(
                select(User).where(User.id == user_id, User.is_active)
            )
            user = result.scalar_one_or_none()

            # Always return success for security (don't reveal if user exists)
            if not user:
                logger.warning("Password reset requested for non-existent user")
                return {"success": True}

            # Generate secure reset token
            token = self._generate_secure_token()
            expires_at = datetime.now(timezone.utc) + timedelta(
                hours=self.token_expiry_hours
            )

            # Create reset token record
            reset_token = PasswordResetToken(
                tenant_id=user.tenant_id,
                token=token,
                user_id=user.id,
                expires_at=expires_at,
                is_used=False,
            )
            db.add(reset_token)
            await db.commit()

            # Send reset email
            background_tasks.add_task(
                self._send_password_reset_email_async,
                user.id,
                token,
                request,
            )

            logger.info(f"Password reset token generated for user: {user.email}")
            return {"success": True, "user_id": user.id}

        except Exception as e:
            await db.rollback()
            logger.error(f"Password reset request failed for {user.email}: {e}")
            return {"success": False, "error": str(e)}

    async def verify_reset_token(
        self, db: AsyncSession, token: str
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Verify if a reset token is valid"""
        try:
            # Get token with full user information
            result = await db.execute(
                select(PasswordResetToken, User)
                .options(joinedload(User.tenant))  # Eager load tenant if needed
                .join(User, PasswordResetToken.user_id == User.id)
                .where(
                    PasswordResetToken.token == token,
                    PasswordResetToken.expires_at > datetime.now(timezone.utc),
                    PasswordResetToken.is_used == False,
                )
            )
            token_info = result.first()

            if token_info:
                token_record, user = token_info

                # Return comprehensive user info
                user_info = {
                    "email": user.email,
                    "id": str(user.id),
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "tenant_id": str(user.tenant_id) if user.tenant_id else None,
                    "is_active": user.is_active,
                    "role": (
                        user.role.value
                        if hasattr(user.role, "value")
                        else str(user.role)
                    ),
                }

                # Add tenant info if available
                if hasattr(user, "tenant") and user.tenant:
                    user_info["tenant"] = {
                        "id": str(user.tenant.id),
                        "name": user.tenant.name,
                        "slug": user.tenant.slug,
                    }

                logger.info(f"Token verified for user: {user.email}")
                return True, user_info
            else:
                logger.warning(f"Invalid or expired token: {token[:10]}...")
                return False, None

        except Exception as e:
            logger.error(f"Token verification with info failed: {e}")
            return False, None

    async def complete_password_reset(
        self,
        db: AsyncSession,
        token: str,
        new_password: str,
        background_tasks: BackgroundTasks,
    ) -> Dict[str, Any]:
        """Complete password reset with new password"""
        try:
            # Verify token
            result = await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token == token,
                    PasswordResetToken.expires_at > datetime.now(timezone.utc),
                    PasswordResetToken.is_used == False,
                )
            )
            reset_token = result.scalar_one_or_none()

            if not reset_token:
                return {"success": False, "error": "Invalid or expired reset token"}

            # Get user
            user = await db.get(User, reset_token.user_id)
            if not user or not getattr(user, "is_active"):
                return {"success": False, "error": "User not found or inactive"}

            # Use auth_service to update password (handles security properly)
            await auth_service.update_user_password(
                db, getattr(user, "id"), new_password, revoke_other_sessions=True
            )

            # Mark token as used
            setattr(reset_token, "is_used", True)
            setattr(reset_token, "used_at", datetime.now(timezone.utc).isoformat())

            await db.commit()

            # Send confirmation email
            background_tasks.add_task(
                self._send_password_reset_confirmation_email_sync, str(user.id)
            )

            logger.info(f"Password reset completed for user: {user.email}")
            return {"success": True, "user_id": user.id}

        except HTTPException as e:
            await db.rollback()
            return {"success": False, "error": e.detail}
        except Exception as e:
            await db.rollback()
            logger.error(f"Password reset completion failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_secure_token(self, length: int = 32) -> str:
        """Generate a secure random token"""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def _send_password_reset_email_async(
        self, user_id: UUID, token: str, request: Request
    ):
        """Async function to send password reset email"""
        # Create new database session for background task
        async with AsyncSessionLocal() as db:
            try:
                # Get user with tenant relationship
                result = await db.execute(
                    select(User)
                    .where(User.id == user_id)
                    .options(joinedload(User.tenant))  # Eager load tenant relationship
                )
                user = result.scalar_one_or_none()

                if not user:
                    logger.error(f"User not found for password reset email: {user_id}")
                    return

                user_name = f"{user.first_name} {user.last_name}"
                user_email = user.email

                # Get tenant name
                tenant_name = getattr(user.tenant, "name", None)

                # Get tenant slug
                tenant_slug = getattr(user.tenant, "slug", None)

                # Get user agent and IP address
                user_agent = request.headers.get("User-Agent")
                ip_address = request.headers.get("X-Forwarded-For")

                if not email_settings.SEND_EMAILS:
                    logger.info(f"Email sending disabled. Would send to: {user.email}")
                    return

                response = await email_service.send_password_reset_v2(
                    user_email=user_email,
                    user_name=user_name,
                    reset_token=token,
                    tenant_name=tenant_name,
                    tenant_slug=tenant_slug,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    expiry_hours=self.token_expiry_hours,
                )

                if response.success:
                    logger.info(f"Password reset email sent to: {user.email}")
                else:
                    logger.error(
                        f"Failed to send password reset email: {response.error}"
                    )

            except Exception as e:
                logger.error(f"Error in background email task for user {user_id}: {e}")

    def _send_password_reset_confirmation_email_sync(self, user_id_str: str):
        """SYNC wrapper for sending confirmation email (for BackgroundTasks)"""
        asyncio.create_task(
            self._send_password_reset_confirmation_email_async(UUID(user_id_str))
        )

    async def _send_password_reset_confirmation_email_async(self, user_id: UUID):
        """Async function to send password reset confirmation email"""
        async with AsyncSessionLocal() as db:
            try:
                # Get user with tenant relationship
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()

                if not user:
                    logger.error(f"User not found for confirmation email: {user_id}")
                    return

                # Get tenant name
                tenant_name = getattr(
                    user.tenant, "name", "Dental Clinic Management System"
                )

                template_data = {
                    "user_name": f"{user.first_name} {user.last_name}",
                    "clinic_name": tenant_name,
                    "support_email": email_settings.SUPPORT_EMAIL,
                    "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                }

                from core.email_config import email_settings

                if not email_settings.SEND_EMAILS:
                    logger.info(
                        f"Email sending disabled. Would send confirmation to: {user.email}"
                    )
                    return

                response = await email_service.send_templated_email(
                    EmailType.SECURITY_ALERT,
                    to=[user.email],
                    template_data=template_data,
                )

                if response.success:
                    logger.info(f"Password reset confirmation sent to: {user.email}")
                else:
                    logger.error(f"Failed to send confirmation email: {response.error}")

            except Exception as e:
                logger.error(
                    f"Error in background confirmation email for user {user_id}: {e}"
                )

    async def cleanup_expired_tokens(self, db: AsyncSession) -> int:
        """Clean up expired password reset tokens"""
        try:
            result = await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.expires_at <= datetime.utcnow(),
                    PasswordResetToken.is_used == False,
                )
            )
            expired_tokens = result.scalars().all()

            count = len(expired_tokens)
            for token in expired_tokens:
                await db.delete(token)

            await db.commit()
            logger.info(f"Cleaned up {count} expired password reset tokens")
            return count

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return 0


# Global service instance
password_reset_service = PasswordResetService()
