# src/services/user_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status
from models.user import User, StaffRole
from schemas.user_schemas import UserCreate, UserUpdate, UserSearch
from utils.logger import setup_logger
from .base_service import BaseService
from .auth_service import auth_service, password_policy_service

logger = setup_logger("USER_SERVICE")


class UserService(BaseService):
    def __init__(self):
        super().__init__(User)

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get user by email"""
        try:
            result = await db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None

    async def get_by_role(
        self, db: AsyncSession, role: StaffRole, skip: int = 0, limit: int = 100
    ) -> List[User]:
        """Get users by role"""
        try:
            result = await db.execute(
                select(User)
                .where(User.role == role, User.is_active)
                .offset(skip)
                .limit(limit)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting users by role {role}: {e}")
            return []

    async def get_by_id(self, db: AsyncSession, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        try:
            result = await db.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {e}")
            return None

    async def update_user(
        self, db: AsyncSession, user_id: UUID, user_data: UserUpdate
    ) -> Optional[User]:
        """Update user information"""
        user = await self.get_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        update_data = user_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await db.commit()
        await db.refresh(user)

        logger.info(f"Updated user: {user.email}")
        return user

    async def change_password(
        self, db: AsyncSession, user_id: UUID, password_data: str
    ) -> bool:
        """Change user password"""
        user = await self.get_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Validate password strength
        is_valid, errors = password_policy_service.validate_password_strength(
            password_data
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password does not meet security requirements: "
                + "; ".join(errors),
            )

        # Verify current password
        if not auth_service.verify_password(
            password_data, getattr(user, "hashed_password")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        # Update password
        user.hashed_password = auth_service.get_password_hash(password_data)
        user.settings["password_changed_at"] = datetime.now(timezone.utc).isoformat()
        await db.commit()

        logger.info(f"Password changed for user: {user.email}")
        return True

    async def deactivate_user(self, db: AsyncSession, user_id: UUID) -> bool:
        """Deactivate user account"""
        user = await self.get_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user.is_active = False
        await db.commit()

        logger.info(f"Deactivated user: {user.email}")
        return True

    async def get_available_dentists(self, db: AsyncSession) -> List[User]:
        """Get available dentists"""
        try:
            result = await db.execute(
                select(User)
                .where(
                    User.role == StaffRole.DENTIST, User.is_active, User.is_available
                )
                .order_by(User.first_name, User.last_name)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting available dentists: {e}")
            return []

    async def search_users(
        self,
        db: AsyncSession,
        search_params: UserSearch,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> List[User]:
        """Search Users with various filters - FIXED boolean handling"""
        try:
            query = select(User).where(User.tenant_id == tenant_id)

            # Text search
            if search_params.query:
                search_term = f"%{search_params.query}%"
                query = query.where(
                    or_(
                        User.first_name.ilike(search_term),
                        User.last_name.ilike(search_term),
                        User.email.ilike(search_term),
                        User.contact_number.ilike(search_term),
                    )
                )

            # Role filter
            if search_params.role:
                query = query.where(User.role == search_params.role)

            # Status filter - FIXED: Handle both boolean and string values
            if search_params.is_active is not None:
                # Convert to boolean if it's a string
                if isinstance(search_params.is_active, str):
                    if search_params.is_active.lower() in ["true", "1", "yes"]:
                        is_active_bool = True
                    elif search_params.is_active.lower() in ["false", "0", "no"]:
                        is_active_bool = False
                    else:
                        # Default to True if unclear
                        is_active_bool = True
                else:
                    is_active_bool = bool(search_params.is_active)

                query = query.where(User.is_active == is_active_bool)

            query = (
                query.offset(skip)
                .limit(limit)
                .order_by(User.last_name, User.first_name)
            )
            result = await db.execute(query)
            users = result.scalars().all()

            logger.info(
                f"Found {len(users)} users with filters: role={search_params.role}, is_active={search_params.is_active}"
            )
            return users

        except Exception as e:
            logger.error(f"Error searching Users: {e}")
            return []


user_service = UserService()
