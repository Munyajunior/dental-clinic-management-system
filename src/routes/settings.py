# src/routes/settings.py
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional
from uuid import UUID

from db.database import get_db
from schemas.settings_schemas import (
    SettingsCategory,
    BulkSettingsUpdate,
    SettingsAuditResponse,
)
from services.settings_service import settings_service
from services.auth_service import auth_service
from dependencies.tenant_deps import get_current_tenant

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "/",
    summary="Get tenant settings",
    description="Get all settings for current tenant",
)
async def get_settings(
    category: Optional[SettingsCategory] = Query(None),
    key: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Get settings endpoint"""
    settings = await settings_service.get_tenant_settings(db, tenant.id, category, key)
    return {"settings": settings}


@router.get(
    "/{category}/{key}",
    summary="Get specific setting",
    description="Get a specific setting value",
)
async def get_setting(
    category: SettingsCategory,
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Any:
    """Get specific setting endpoint"""
    value = await settings_service.get_setting(db, tenant.id, category, key)
    return {"value": value}


@router.put(
    "/{category}/{key}",
    summary="Update setting",
    description="Update a specific setting",
)
async def update_setting(
    category: SettingsCategory,
    key: str,
    value: Any,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Update setting endpoint"""
    setting = await settings_service.create_or_update_setting(
        db, tenant.id, category, key, value, current_user.id
    )
    return {"message": "Setting updated successfully", "setting": setting}


@router.post(
    "/bulk",
    summary="Bulk update settings",
    description="Update multiple settings at once",
)
async def bulk_update_settings(
    update_data: BulkSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Bulk update settings endpoint"""
    settings = await settings_service.bulk_update_settings(
        db, tenant.id, update_data.settings, current_user.id, update_data.change_reason
    )
    return {
        "message": f"Updated {len(settings)} settings",
        "updated_settings": settings,
    }


@router.post(
    "/reset",
    summary="Reset settings to defaults",
    description="Reset settings to their default values",
)
async def reset_settings(
    categories: Optional[List[SettingsCategory]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Reset settings endpoint"""
    settings = await settings_service.reset_to_defaults(
        db, tenant.id, current_user.id, categories
    )
    return {
        "message": f"Reset {len(settings)} settings to defaults",
        "reset_settings": settings,
    }


@router.get(
    "/audit/history",
    response_model=List[SettingsAuditResponse],
    summary="Get settings audit history",
    description="Get audit history for settings changes",
)
async def get_settings_audit(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
    tenant: Any = Depends(get_current_tenant),
) -> Any:
    """Get settings audit history endpoint"""
    audit_entries = await settings_service.get_settings_audit(
        db, tenant.id, skip, limit
    )
    return audit_entries
