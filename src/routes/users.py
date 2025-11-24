# src/routes/users.py
from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any, Dict, Optional
from uuid import UUID
from db.database import get_db
from schemas.user_schemas import (
    UserCreate,
    UserUpdate,
    UserPublic,
    UserSearch,
    StaffRole,
)
from services.user_service import user_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("_USER_ROUTES")
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
    role: Optional[StaffRole] = None,
    is_active: Optional[Any] = None,  # Allow any type for flexible handling
    query: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List users endpoint with flexible boolean handling"""
    try:
        # Convert is_active to boolean if it's a string
        is_active_bool = None
        if is_active is not None:
            if isinstance(is_active, str):
                if is_active.lower() in ["true", "1", "yes"]:
                    is_active_bool = True
                elif is_active.lower() in ["false", "0", "no"]:
                    is_active_bool = False
                else:
                    # If it's not a clear boolean string, treat as True for safety
                    is_active_bool = True
            else:
                is_active_bool = bool(is_active)

        search_params = UserSearch(query=query, role=role, is_active=is_active_bool)
        users = await user_service.search_users(
            db, search_params, current_user.tenant_id, skip, limit
        )
        users_list = [UserPublic.from_orm_safe(user) for user in users]
        return users_list
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        # Return empty list on error rather than crashing
        return []


@router.post(
    "/",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
    description="Create a new user in current tenant",
)
async def create_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
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

    # Validate role-specific requirements
    if user_data.role in [
        StaffRole.DENTIST,
        StaffRole.THERAPIST,
        StaffRole.HYGIENIST,
    ]:
        if not user_data.specialization:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Specialization is required for dentist role",
            )

    user = await auth_service.create_user(
        db=db,
        user_data=user_data,
        background_tasks=background_tasks,
        tenant_id=current_user.tenant_id,
        create_default_user=False,
    )
    return UserPublic.from_orm_safe(user)


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
    return UserPublic.from_orm_safe(user)


@router.get(
    "/dentists",
    response_model=List[UserPublic],
    summary="Get dentists",
    description="Get list of available dentists",
)
async def get_dentists(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> List[UserPublic]:
    """Get dentists endpoint"""
    try:
        dentists = await user_service.get_available_dentists(db)
        return [UserPublic.from_orm_safe(dentist) for dentist in dentists]
    except Exception as e:
        logger.error(f"Failed to fetch available dentist: {str(e)}")
        return []


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

    # Validate role-specific requirements for dentists
    if user_data.role in [
        StaffRole.DENTIST,
        StaffRole.THERAPIST,
        StaffRole.HYGIENIST,
    ]:
        if not user_data.specialization:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Specialization is required for dentist role",
            )

    user = await user_service.update_user(db, user_id, user_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserPublic.from_orm_safe(user)


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
