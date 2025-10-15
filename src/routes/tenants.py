# src/routes/tenants.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any
from uuid import UUID
from db.database import get_db
from schemas.tenant_schemas import (
    TenantCreate,
    TenantUpdate,
    TenantInDB,
    TenantPublic,
    TenantStats,
)
from services.tenant_service import tenant_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "/",
    response_model=TenantPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create tenant",
    description="Create a new tenant (clinic)",
)
@limiter.limit("5/minute")
async def create_tenant(
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create new tenant endpoint"""
    # Only allow admins or specific roles to create tenants
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create tenants",
        )

    tenant = await tenant_service.create_tenant(db, tenant_data)
    return TenantPublic.from_orm(tenant)


@router.get(
    "/",
    response_model=List[TenantPublic],
    summary="List tenants",
    description="Get list of all tenants (filtered by permissions)",
)
async def list_tenants(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List tenants endpoint"""
    # Implementation depends on user permissions
    tenants = await tenant_service.get_multi(db, skip=skip, limit=limit)
    return [TenantPublic.from_orm(tenant) for tenant in tenants]


@router.get(
    "/{tenant_id}",
    response_model=TenantPublic,
    summary="Get tenant",
    description="Get tenant by ID",
)
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get tenant by ID endpoint"""
    tenant = await tenant_service.get(db, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )
    return TenantPublic.from_orm(tenant)


@router.put(
    "/{tenant_id}",
    response_model=TenantPublic,
    summary="Update tenant",
    description="Update tenant information",
)
async def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update tenant endpoint"""
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update tenants",
        )

    tenant = await tenant_service.update(db, tenant_id, tenant_data)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )
    return TenantPublic.from_orm(tenant)


@router.get(
    "/{tenant_id}/stats",
    response_model=TenantStats,
    summary="Get tenant statistics",
    description="Get comprehensive statistics for a tenant",
)
async def get_tenant_stats(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get tenant statistics endpoint"""
    stats = await tenant_service.get_tenant_stats(db, tenant_id)
    return stats


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tenant",
    description="Delete tenant (soft delete or archive)",
)
async def delete_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> None:
    """Delete tenant endpoint"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete tenants",
        )

    deleted = await tenant_service.delete(db, tenant_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )
