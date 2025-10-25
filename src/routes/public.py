# src/routes/public.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db_session  # Session without tenant context
from typing import Any
from schemas.tenant_schemas import TenantCreate, TenantPublic
from services.tenant_service import tenant_service
from utils.rate_limiter import limiter
from utils.logger import setup_logger

logger = setup_logger("PUBLIC ROUTES")

router = APIRouter(prefix="/public", tags=["public"])


@router.post(
    "/tenants/register",
    response_model=TenantPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register new clinic",
    description="Public endpoint for clinics to create their account",
)
@limiter.limit("3/hour")  # Prevent spam
async def register_tenant(
    request: Request,
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_db_session),  # Use system session
) -> Any:
    """Public tenant registration endpoint"""
    try:
        # Additional validation for public registration
        if await tenant_service.get_by_slug(db, tenant_data.slug):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Clinic URL already exists"
            )

        # Create tenant with admin user
        tenant = await tenant_service.create_tenant_with_admin(db, tenant_data)

        logger.info(f"New tenant registered: {tenant.name} ({tenant.slug})")

        return TenantPublic.from_orm(tenant)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Tenant registration failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create clinic account. Please try again or contact support.",
        )
