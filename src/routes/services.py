# src/routes/services.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any
from uuid import UUID
from db.database import get_db
from schemas.service_schemas import (
    ServiceCreate,
    ServiceUpdate,
    ServicePublic,
    ServiceCategorySummary,
)
from services.service_service import service_service
from services.auth_service import auth_service
from utils.rate_limiter import limiter

router = APIRouter(prefix="/services", tags=["services"])


@router.get(
    "/",
    response_model=List[ServicePublic],
    summary="List services",
    description="Get list of all services",
)
async def list_services(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """List services endpoint"""
    filters = {}
    if category:
        filters["category"] = category
    if status:
        filters["status"] = status

    services = await service_service.get_multi(
        db, skip=skip, limit=limit, filters=filters
    )
    return [ServicePublic.from_orm(service) for service in services]


@router.post(
    "/",
    response_model=ServicePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create service",
    description="Create a new dental service",
)
async def create_service(
    service_data: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Create service endpoint"""
    # Only admins and managers can create services
    if current_user.role not in ["admin", "manager", "dentist", "receptionist"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create services",
        )

    if not service_data.tenant_id:
        service_data.tenant_id = current_user.tenant_id

    service = await service_service.create_service(db, service_data)
    return ServicePublic.from_orm(service)


@router.get(
    "/{service_id}",
    response_model=ServicePublic,
    summary="Get service",
    description="Get service by ID",
)
async def get_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get service by ID endpoint"""
    service = await service_service.get(db, service_id)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        )
    return ServicePublic.from_orm(service)


@router.put(
    "/{service_id}",
    response_model=ServicePublic,
    summary="Update service",
    description="Update service information",
)
async def update_service(
    service_id: UUID,
    service_data: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Update service endpoint"""
    # Only admins and managers, dentist, receptionist can update services
    if current_user.role not in ["admin", "manager", "dentist", "receptionist"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update services",
        )

    service = await service_service.update(db, service_id, service_data)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        )
    return ServicePublic.from_orm(service)


@router.get(
    "/categories/summary",
    response_model=List[ServiceCategorySummary],
    summary="Get service categories summary",
    description="Get summary of services by category",
)
async def get_categories_summary(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get categories summary endpoint"""
    summary = await service_service.get_categories_summary(db)
    return summary


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate service",
    description="Deactivate service (soft delete)",
)
async def deactivate_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> None:
    """Deactivate service endpoint"""
    # Only admins and managers can deactivate services
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to deactivate services",
        )

    update_data = ServiceUpdate(status="inactive")
    service = await service_service.update(db, service_id, update_data)
    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        )
