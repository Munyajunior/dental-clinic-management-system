# src/routes/users.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any
from uuid import UUID
from db.database import get_db
from schemas.user_schemas import (
    UserCreate,
    UserUpdate,
    UserPublic,
)
from services.user_service import user_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    response_model=List[UserPublic],
    summary="List users",
    description="Get list of all users in current tenant",
)
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List users endpoint"""
    users = await user_service.get_multi(db, skip=skip, limit=limit)
    return [UserPublic.from_orm(user) for user in users]


@router.post(
    "/",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
    description="Create a new user in current tenant",
)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create user endpoint"""
    # Check permissions
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create users",
        )

    user = await user_service.create_user(db, user_data)
    return UserPublic.from_orm(user)


@router.get(
    "/{user_id}",
    response_model=UserPublic,
    summary="Get user",
    description="Get user by ID",
)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get user by ID endpoint"""
    user = await user_service.get(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserPublic.from_orm(user)


@router.put(
    "/{user_id}",
    response_model=UserPublic,
    summary="Update user",
    description="Update user information",
)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update user endpoint"""
    # Users can update their own profile, admins can update any
    if current_user.id != user_id and current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user",
        )

    user = await user_service.update_user(db, user_id, user_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserPublic.from_orm(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user",
    description="Deactivate user account",
)
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> None:
    """Deactivate user endpoint"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to deactivate users",
        )

    await user_service.deactivate_user(db, user_id)
