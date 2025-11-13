# src/schemas/tenant_schemas.py
from pydantic import EmailStr, field_validator
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from models.tenant import TenantTier, TenantStatus
from .base_schemas import BaseSchema, TimestampMixin, IDMixin


class TenantBase(BaseSchema):
    """Base tenant schema"""

    name: str
    slug: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    office_hours: Optional[Dict[str, Any]] = None


class TenantCreate(TenantBase):
    """Schema for creating a tenant"""

    tier: TenantTier = TenantTier.BASIC
    subscription_id: Optional[str] = None
    billing_cycle: str = "monthly"
    max_users: int = 5
    max_patients: int = 1000

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "Slug can only contain alphanumeric characters, underscores and hyphens"
            )
        return v.lower()


class TenantUpdate(BaseSchema):
    """Schema for updating a tenant"""

    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    tier: Optional[TenantTier] = None
    status: Optional[TenantStatus] = None
    billing_cycle: Optional[str] = None
    max_users: Optional[int] = None
    max_patients: Optional[int] = None
    settings: Optional[Dict[str, Any]] = None
    features: Optional[Dict[str, Any]] = None


class TenantInDB(IDMixin, TenantBase, TimestampMixin):
    """Tenant schema for database representation"""

    tier: TenantTier
    status: TenantStatus
    subscription_id: Optional[str] = None
    billing_cycle: str
    max_users: int
    max_patients: int
    isolation_level: str
    settings: Dict[str, Any]
    features: Dict[str, Any]
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None


class TenantPublic(BaseSchema):
    """Public tenant schema (for listing)"""

    id: UUID
    name: str
    slug: str
    tier: TenantTier
    status: TenantStatus


class TenantStats(BaseSchema):
    """Tenant statistics"""

    total_users: int
    total_patients: int
    total_appointments: int
    total_invoices: int
    monthly_revenue: float
    active_patients: int


class TenantConfig(BaseSchema):
    """Tenant configuration schema"""

    isolation_level: str = "shared"
    email_notifications: bool = True
    sms_notifications: bool = False
    auto_reminders: bool = True
    invoice_auto_generate: bool = False


class TenantSubscription(BaseSchema):
    """Tenant subscription details"""

    tier: TenantTier
    status: TenantStatus
    billing_cycle: str
    max_users: int
    max_patients: int
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None
