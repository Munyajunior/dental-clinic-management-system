# src/services/user_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from models.user import User, StaffRole
from schemas.user_schemas import UserCreate, UserUpdate, UserPasswordChange
from utils.logger import setup_logger
from .base_service import BaseService
from .auth_service import auth_service

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
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting users by role {role}: {e}")
            return []

    async def create_user(self, db: AsyncSession, user_data: UserCreate) -> User:
        """Create new user with hashed password"""
        # Check if user already exists
        existing_user = await self.get_by_email(db, user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists",
            )

        # Hash password and create user
        hashed_password = auth_service.get_password_hash(user_data.password)
        user_dict = user_data.model_dump(exclude={"password"})
        user_dict["hashed_password"] = hashed_password

        user = User(**user_dict)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"Created new user: {user.email} ({user.role})")
        return user

    async def update_user(
        self, db: AsyncSession, user_id: UUID, user_data: UserUpdate
    ) -> Optional[User]:
        """Update user information"""
        user = await self.get(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        update_data = user_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await db.commit()
        await db.refresh(user)

        logger.info(f"Updated user: {user.email}")
        return user

    async def change_password(
        self, db: AsyncSession, user_id: UUID, password_data: UserPasswordChange
    ) -> bool:
        """Change user password"""
        user = await self.get(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Verify current password
        if not auth_service.verify_password(
            password_data.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        # Update password
        user.hashed_password = auth_service.get_password_hash(
            password_data.new_password
        )
        await db.commit()

        logger.info(f"Password changed for user: {user.email}")
        return True

    async def deactivate_user(self, db: AsyncSession, user_id: UUID) -> bool:
        """Deactivate user account"""
        user = await self.get(db, user_id)
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
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting available dentists: {e}")
            return []


user_service = UserService()
