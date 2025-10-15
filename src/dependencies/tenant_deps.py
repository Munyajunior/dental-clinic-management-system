# src/dependencies/tenant_deps.py
from fastapi import Depends, HTTPException, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from sqlalchemy import select
from db.database import get_db, tenant_id_var
from models.tenant import Tenant
import uuid


async def get_current_tenant(
    request: Request,
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    x_tenant_slug: str = Header(None, alias="X-Tenant-Slug"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Dependency to get and verify current tenant"""
    # Try to get tenant ID from context first (set by middleware)
    tenant_id = tenant_id_var.get()

    # If not in context, try headers
    if not tenant_id:
        tenant_id = x_tenant_id

    # If still no tenant ID, try slug
    tenant_slug = x_tenant_slug

    if not tenant_id and not tenant_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant identifier required. Provide X-Tenant-ID or X-Tenant-Slug header",
        )

    try:
        if tenant_id:
            # Validate UUID format
            tenant_uuid = uuid.UUID(tenant_id)
            result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        else:
            # Find by slug
            result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))

        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
            )

        if tenant.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not active"
            )

        # Set tenant context for RLS
        tenant_id_var.set(str(tenant.id))

        return tenant

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant ID format"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving tenant: {str(e)}",
        )


async def require_tenant_context(tenant: Tenant = Depends(get_current_tenant)):
    """Dependency that requires valid tenant context"""
    return tenant


async def optional_tenant_context(
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    x_tenant_slug: str = Header(None, alias="X-Tenant-Slug"),
) -> Optional[Tenant]:
    """Optional tenant context for public endpoints"""
    if not x_tenant_id and not x_tenant_slug:
        return None

    # For optional context, we need to create a session
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            if x_tenant_id:
                tenant_uuid = uuid.UUID(x_tenant_id)
                result = await db.execute(
                    select(Tenant).where(Tenant.id == tenant_uuid)
                )
            else:
                result = await db.execute(
                    select(Tenant).where(Tenant.slug == x_tenant_slug)
                )

            tenant = result.scalar_one_or_none()

            if tenant and tenant.status == "active":
                tenant_id_var.set(str(tenant.id))
                return tenant

            return None

        except (ValueError, Exception):
            return None
