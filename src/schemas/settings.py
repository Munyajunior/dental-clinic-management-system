# src/schemas/settings_schemas.py
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


class SettingsCategory(str, Enum):
    GENERAL = "general"
    CLINIC = "clinic"
    NOTIFICATIONS = "notifications"
    BILLING = "billing"
    SECURITY = "security"
    INTEGRATIONS = "integrations"


class SettingsBase(BaseModel):
    """Base settings schema"""

    category: SettingsCategory
    settings_key: str
    settings_value: Dict[str, Any]
    description: Optional[str] = None
    is_encrypted: bool = False


class SettingsCreate(SettingsBase):
    """Schema for creating settings"""

    created_by: UUID


class SettingsUpdate(BaseModel):
    """Schema for updating settings"""

    settings_value: Dict[str, Any]
    description: Optional[str] = None
    is_encrypted: Optional[bool] = None
    updated_by: UUID


class SettingsInDB(SettingsBase):
    """Settings schema for database representation"""

    id: UUID
    tenant_id: UUID
    created_by: UUID
    updated_by: Optional[UUID] = None
    version: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class BulkSettingsUpdate(BaseModel):
    """Bulk settings update schema"""

    settings: List[Dict[str, Any]]
    updated_by: UUID
    change_reason: Optional[str] = None


class SettingsAuditResponse(BaseModel):
    """Settings audit response schema"""

    id: UUID
    settings_id: UUID
    old_value: Optional[Dict[str, Any]]
    new_value: Dict[str, Any]
    change_type: str
    change_reason: Optional[str]
    changed_by: UUID
    changed_at: datetime
    changer_name: str


class ClientSettingsCache(BaseModel):
    """Client-side settings cache schema"""

    settings: Dict[str, Any]
    last_updated: datetime
    version: str
    cache_key: str


# Predefined settings templates
SETTINGS_TEMPLATES = {
    SettingsCategory.GENERAL: {
        "language": {"type": "string", "default": "en", "options": ["en", "es", "fr"]},
        "theme": {
            "type": "string",
            "default": "light",
            "options": ["light", "dark", "system"],
        },
        "auto_save": {"type": "boolean", "default": True},
        "auto_save_interval": {"type": "integer", "default": 5, "min": 1, "max": 60},
        "date_format": {
            "type": "string",
            "default": "YYYY-MM-DD",
            "options": ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY"],
        },
        "time_format": {"type": "string", "default": "24h", "options": ["24h", "12h"]},
    },
    SettingsCategory.CLINIC: {
        "name": {"type": "string", "default": ""},
        "address": {"type": "string", "default": ""},
        "phone": {"type": "string", "default": ""},
        "email": {"type": "string", "default": ""},
        "website": {"type": "string", "default": ""},
        "business_hours": {"type": "object", "default": {}},
        "timezone": {"type": "string", "default": "UTC"},
    },
    SettingsCategory.NOTIFICATIONS: {
        "email_enabled": {"type": "boolean", "default": True},
        "smtp_server": {"type": "string", "default": ""},
        "smtp_port": {"type": "integer", "default": 587},
        "email_from": {"type": "string", "default": ""},
        "appointment_reminders": {"type": "boolean", "default": True},
        "appointment_confirmations": {"type": "boolean", "default": True},
        "invoice_notifications": {"type": "boolean", "default": True},
        "payment_notifications": {"type": "boolean", "default": True},
        "reminder_days_ahead": {"type": "integer", "default": 1, "min": 1, "max": 7},
    },
    SettingsCategory.BILLING: {
        "tax_enabled": {"type": "boolean", "default": True},
        "tax_rate": {"type": "number", "default": 0.0, "min": 0, "max": 100},
        "invoice_prefix": {"type": "string", "default": "INV"},
        "default_due_days": {"type": "integer", "default": 30, "min": 1, "max": 90},
        "late_fee_enabled": {"type": "boolean", "default": False},
        "late_fee_rate": {"type": "number", "default": 5.0, "min": 0, "max": 50},
        "currency": {
            "type": "string",
            "default": "USD",
            "options": ["USD", "EUR", "GBP"],
        },
    },
    SettingsCategory.SECURITY: {
        "session_timeout": {"type": "integer", "default": 30, "min": 5, "max": 480},
        "auto_logout": {"type": "boolean", "default": True},
        "min_password_length": {"type": "integer", "default": 8, "min": 6, "max": 20},
        "require_special_chars": {"type": "boolean", "default": False},
        "require_numbers": {"type": "boolean", "default": False},
        "password_expiry": {"type": "integer", "default": 90, "min": 0, "max": 365},
        "max_login_attempts": {"type": "integer", "default": 5, "min": 3, "max": 10},
        "encryption_enabled": {"type": "boolean", "default": True},
    },
}
