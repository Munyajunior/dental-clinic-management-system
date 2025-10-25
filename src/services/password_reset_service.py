# src/services/password_reset_service.py
import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
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
        self.token_expiry_hours = 24  # Token expires after 24 hours

    async def request_password_reset(
        self, db: AsyncSession, email: str
    ) -> Dict[str, Any]:
        """Request password reset for a user"""
        try:
            # Find user by email
            result = await db.execute(
                select(User).where(User.email == email, User.is_active == True)
            )
            user = result.scalar_one_or_none()

            # Always return success for security (don't reveal if user exists)
            if not user:
                logger.warning(
                    f"Password reset requested for non-existent email: {email}"
                )
                return {"success": True}

            # Generate secure reset token
            token = self._generate_secure_token()
            expires_at = datetime.utcnow() + timedelta(hours=self.token_expiry_hours)

            # Create reset token record
            reset_token = PasswordResetToken(
                token=token, user_id=user.id, expires_at=expires_at, is_used=False
            )
            db.add(reset_token)
            await db.commit()

            # Send reset email
            await self._send_password_reset_email(user, token)

            logger.info(f"Password reset token generated for user: {user.email}")
            return {"success": True, "user_id": user.id}

        except Exception as e:
            await db.rollback()
            logger.error(f"Password reset request failed for {email}: {e}")
            return {"success": False, "error": str(e)}

    async def verify_reset_token(self, db: AsyncSession, token: str) -> bool:
        """Verify if a reset token is valid"""
        try:
            result = await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token == token,
                    PasswordResetToken.expires_at > datetime.utcnow(),
                    PasswordResetToken.is_used == False,
                )
            )
            reset_token = result.scalar_one_or_none()

            return reset_token is not None

        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return False

    async def complete_password_reset(
        self, db: AsyncSession, token: str, new_password: str
    ) -> Dict[str, Any]:
        """Complete password reset with new password"""
        try:
            # Verify token
            result = await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token == token,
                    PasswordResetToken.expires_at > datetime.utcnow(),
                    PasswordResetToken.is_used == False,
                )
            )
            reset_token = result.scalar_one_or_none()

            if not reset_token:
                return {"success": False, "error": "Invalid or expired reset token"}

            # Get user
            user = await db.get(User, reset_token.user_id)
            if not user or not user.is_active:
                return {"success": False, "error": "User not found or inactive"}

            # Update password
            user.hashed_password = auth_service.get_password_hash(new_password)
            reset_token.is_used = True
            reset_token.used_at = datetime.utcnow()

            await db.commit()

            # Send confirmation email
            await self._send_password_reset_confirmation_email(user)

            logger.info(f"Password reset completed for user: {user.email}")
            return {"success": True, "user_id": user.id}

        except Exception as e:
            await db.rollback()
            logger.error(f"Password reset completion failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_secure_token(self, length: int = 32) -> str:
        """Generate a secure random token"""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    async def _send_password_reset_email(self, user: User, token: str) -> bool:
        """Send password reset email"""
        try:
            # Create deep link for desktop app
            deep_link = URLSchemeHandler.create_deep_link("reset-password", token=token)
            # Get user's tenant for context
            tenant_name = getattr(
                user.tenant, "name", "Dental Clinic Management System"
            )

            template_data = {
                "user_name": f"{user.first_name} {user.last_name}",
                "reset_token": token,
                "deep_link_url": deep_link,
                "expiry_hours": self.token_expiry_hours,
                "clinic_name": tenant_name,
                "support_email": "support@kwantabit.com",
                "whatsapp_support": "+237 690908721",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
            }

            response = await email_service.send_templated_email(
                EmailType.PASSWORD_RESET, to=[user.email], template_data=template_data
            )

            if response.success:
                logger.info(f"Password reset email sent to: {user.email}")
                return True
            else:
                logger.error(f"Failed to send password reset email: {response.error}")
                return False
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            return False

    async def _send_password_reset_confirmation_email(self, user: User) -> bool:
        """Send password reset confirmation email"""
        try:
            # Get user's tenant for context
            tenant_name = getattr(
                user.tenant, "name", "Dental Clinic Management System"
            )

            template_data = {
                "user_name": f"{user.first_name} {user.last_name}",
                "clinic_name": tenant_name,
                "support_email": "support@kwantabit.com",
                "whatsapp_support": "+237 690908721",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
            }

            response = await email_service.send_templated_email(
                EmailType.SECURITY_ALERT, to=[user.email], template_data=template_data
            )

            if response.success:
                logger.info(f"Password reset confirmation sent to: {user.email}")
                return True
            else:
                logger.error(f"Failed to send confirmation email: {response.error}")
                return False

        except Exception as e:
            logger.error(f"Error sending confirmation email: {e}")
            return False

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
