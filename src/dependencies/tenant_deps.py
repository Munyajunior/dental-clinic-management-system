# src/dependencies/tenant_deps.py
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db, tenant_id_var
from models.tenant import Tenant
import uuid


async def get_current_tenant(
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Dependency to get and verify current tenant"""
    tenant_id = tenant_id_var.get() or x_tenant_id

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant identifier required")

    try:
        # Validate UUID format
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        # If not UUID, try to find by slug
        result = await db.execute(select(Tenant).where(Tenant.slug == tenant_id))
        tenant = result.scalar_one_or_none()
    else:
        # Find by UUID
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")

    return tenant


async def require_tenant_context(tenant: Tenant = Depends(get_current_tenant)):
    """Dependency that requires valid tenant context"""
    # Set the tenant context for RLS
    tenant_id_var.set(str(tenant.id))
    return tenant
