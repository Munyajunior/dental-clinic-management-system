# src/services/settings_service.py
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException, status

from models.settings import TenantSettings, SettingsAudit
from schemas.settings_schemas import (
    SettingsCreate,
    SettingsUpdate,
    BulkSettingsUpdate,
    SettingsCategory,
    SETTINGS_TEMPLATES,
)
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("SETTINGS_SERVICE")


class SettingsService(BaseService):
    def __init__(self):
        super().__init__(TenantSettings)

    async def get_tenant_settings(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        category: Optional[SettingsCategory] = None,
        key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get settings for a tenant with optional filtering"""
        try:
            query = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)

            if category:
                query = query.where(TenantSettings.category == category)
            if key:
                query = query.where(TenantSettings.settings_key == key)

            result = await db.execute(query)
            settings = result.scalars().all()

            # Convert to nested dictionary
            settings_dict = {}
            for setting in settings:
                if setting.category not in settings_dict:
                    settings_dict[setting.category] = {}
                settings_dict[setting.category][
                    setting.settings_key
                ] = setting.settings_value

            return settings_dict

        except Exception as e:
            logger.error(f"Error getting tenant settings: {e}")
            return {}

    async def get_setting(
        self, db: AsyncSession, tenant_id: UUID, category: SettingsCategory, key: str
    ) -> Optional[Any]:
        """Get a specific setting value"""
        try:
            result = await db.execute(
                select(TenantSettings).where(
                    and_(
                        TenantSettings.tenant_id == tenant_id,
                        TenantSettings.category == category,
                        TenantSettings.settings_key == key,
                    )
                )
            )
            setting = result.scalar_one_or_none()

            if setting:
                return setting.settings_value
            else:
                # Return default value from template if exists
                template = SETTINGS_TEMPLATES.get(category, {}).get(key, {})
                return template.get("default")

        except Exception as e:
            logger.error(f"Error getting setting {category}.{key}: {e}")
            return None

    async def create_or_update_setting(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        category: SettingsCategory,
        key: str,
        value: Any,
        user_id: UUID,
        description: Optional[str] = None,
        is_encrypted: bool = False,
    ) -> TenantSettings:
        """Create or update a setting with validation"""
        # Validate setting against template
        await self._validate_setting(category, key, value)

        # Check if setting exists
        result = await db.execute(
            select(TenantSettings).where(
                and_(
                    TenantSettings.tenant_id == tenant_id,
                    TenantSettings.category == category,
                    TenantSettings.settings_key == key,
                )
            )
        )
        existing_setting = result.scalar_one_or_none()

        if existing_setting:
            # Update existing setting
            old_value = existing_setting.settings_value
            existing_setting.settings_value = value
            existing_setting.description = description
            existing_setting.is_encrypted = is_encrypted
            existing_setting.updated_by = user_id

            # Create audit entry
            await self._create_audit_entry(
                db,
                tenant_id,
                existing_setting.id,
                old_value,
                value,
                "updated",
                user_id,
                "Setting updated via UI",
            )

            await db.commit()
            await db.refresh(existing_setting)
            return existing_setting
        else:
            # Create new setting
            setting_data = SettingsCreate(
                category=category,
                settings_key=key,
                settings_value=value,
                description=description,
                is_encrypted=is_encrypted,
                created_by=user_id,
            )

            setting = TenantSettings(**setting_data.dict(), tenant_id=tenant_id)

            db.add(setting)
            await db.flush()

            # Create audit entry
            await self._create_audit_entry(
                db,
                tenant_id,
                setting.id,
                None,
                value,
                "created",
                user_id,
                "Setting created via UI",
            )

            await db.commit()
            await db.refresh(setting)
            return setting

    async def bulk_update_settings(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        settings_updates: Dict[str, Any],
        user_id: UUID,
        change_reason: Optional[str] = None,
    ) -> List[TenantSettings]:
        """Bulk update multiple settings"""
        updated_settings = []

        for category_str, category_settings in settings_updates.items():
            try:
                category = SettingsCategory(category_str)
            except ValueError:
                logger.warning(f"Invalid settings category: {category_str}")
                continue

            for key, value in category_settings.items():
                try:
                    setting = await self.create_or_update_setting(
                        db, tenant_id, category, key, value, user_id
                    )
                    updated_settings.append(setting)
                except Exception as e:
                    logger.error(f"Failed to update setting {category}.{key}: {e}")
                    continue

        if change_reason and updated_settings:
            # Create bulk audit entry
            await self._create_bulk_audit_entry(
                db, tenant_id, updated_settings, user_id, change_reason
            )

        return updated_settings

    async def reset_to_defaults(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        user_id: UUID,
        categories: Optional[List[SettingsCategory]] = None,
    ) -> List[TenantSettings]:
        """Reset settings to default values"""
        reset_settings = []

        categories_to_reset = categories or list(SettingsCategory)

        for category in categories_to_reset:
            template = SETTINGS_TEMPLATES.get(category, {})

            for key, config in template.items():
                default_value = config.get("default")
                if default_value is not None:
                    try:
                        setting = await self.create_or_update_setting(
                            db,
                            tenant_id,
                            category,
                            key,
                            default_value,
                            user_id,
                            f"Reset to default value",
                        )
                        reset_settings.append(setting)
                    except Exception as e:
                        logger.error(f"Failed to reset setting {category}.{key}: {e}")
                        continue

        # Create audit entry for reset
        if reset_settings:
            await self._create_bulk_audit_entry(
                db, tenant_id, reset_settings, user_id, "Settings reset to defaults"
            )

        return reset_settings

    async def get_settings_audit(
        self, db: AsyncSession, tenant_id: UUID, skip: int = 0, limit: int = 50
    ) -> List[SettingsAudit]:
        """Get settings audit history"""
        try:
            result = await db.execute(
                select(SettingsAudit)
                .where(SettingsAudit.tenant_id == tenant_id)
                .order_by(SettingsAudit.changed_at.desc())
                .offset(skip)
                .limit(limit)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting settings audit: {e}")
            return []

    async def _validate_setting(self, category: SettingsCategory, key: str, value: Any):
        """Validate setting value against template"""
        template = SETTINGS_TEMPLATES.get(category, {}).get(key)

        if not template:
            logger.warning(f"No template found for setting {category}.{key}")
            return

        expected_type = template.get("type")

        # Type validation
        if expected_type == "string" and not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Setting {category}.{key} must be a string",
            )
        elif expected_type == "integer" and not isinstance(value, int):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Setting {category}.{key} must be an integer",
            )
        elif expected_type == "number" and not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Setting {category}.{key} must be a number",
            )
        elif expected_type == "boolean" and not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Setting {category}.{key} must be a boolean",
            )

        # Range validation
        if expected_type in ["integer", "number"]:
            min_val = template.get("min")
            max_val = template.get("max")

            if min_val is not None and value < min_val:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Setting {category}.{key} must be at least {min_val}",
                )
            if max_val is not None and value > max_val:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Setting {category}.{key} must be at most {max_val}",
                )

        # Options validation
        if expected_type == "string" and "options" in template:
            if value not in template["options"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Setting {category}.{key} must be one of: {', '.join(template['options'])}",
                )

    async def _create_audit_entry(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        settings_id: UUID,
        old_value: Any,
        new_value: Any,
        change_type: str,
        changed_by: UUID,
        change_reason: Optional[str] = None,
    ):
        """Create settings audit entry"""
        audit_entry = SettingsAudit(
            tenant_id=tenant_id,
            settings_id=settings_id,
            old_value=old_value,
            new_value=new_value,
            change_type=change_type,
            change_reason=change_reason,
            changed_by=changed_by,
        )
        db.add(audit_entry)

    async def _create_bulk_audit_entry(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        settings: List[TenantSettings],
        changed_by: UUID,
        change_reason: str,
    ):
        """Create bulk audit entry for multiple settings changes"""
        for setting in settings:
            await self._create_audit_entry(
                db,
                tenant_id,
                setting.id,
                None,
                setting.settings_value,
                "updated",
                changed_by,
                change_reason,
            )


settings_service = SettingsService()
