# src/schemas/service_schemas.py
from pydantic import field_validator
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from models.service import ServiceCategory, ServiceStatus
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class ServiceBase(BaseSchema):
    """Base service schema"""

    code: str
    name: str
    description: Optional[str] = None
    category: ServiceCategory
    base_price: Decimal
    duration_minutes: int = 30

    @field_validator("code")
    @classmethod
    def validate_service_code(cls, v: str) -> str:
        if not v:
            raise ValueError("Service code is required")

        if len(v) < 2 or len(v) > 20:
            raise ValueError("Service code must be 2-20 characters long")

        if not re.match(r"^[A-Z0-9_]+$", v):
            raise ValueError(
                "Service code must be all uppercase and contain only letters, numbers, and underscores"
            )

        return v


class ServiceCreate(ServiceBase):
    """Schema for creating a service"""

    is_taxable: bool = True
    tax_rate: Decimal = Decimal("0.0")
    requirements: Optional[Dict[str, Any]] = None
    status: ServiceStatus
    materials: Optional[Dict[str, Any]] = None
    tenant_id: Optional[UUID] = None

    @field_validator("base_price")
    @classmethod
    def validate_base_price(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("Base price cannot be negative")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Duration must be positive")
        return v


class ServiceUpdate(BaseSchema):
    """Schema for updating a service"""

    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[ServiceCategory] = None
    base_price: Optional[Decimal] = None
    duration_minutes: Optional[int] = None
    status: Optional[ServiceStatus] = None
    is_taxable: Optional[bool] = None
    tax_rate: Optional[Decimal] = None
    requirements: Optional[Dict[str, Any]] = None
    materials: Optional[Dict[str, Any]] = None


class ServiceInDB(IDMixin, TenantMixin, ServiceBase, TimestampMixin):
    """Service schema for database representation"""

    status: ServiceStatus
    is_taxable: bool
    tax_rate: Decimal
    requirements: Optional[Dict[str, Any]] = None
    materials: Optional[Dict[str, Any]] = None


class ServicePublic(BaseSchema):
    """Public service schema"""

    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    category: ServiceCategory
    base_price: Decimal
    duration_minutes: int
    status: ServiceStatus


class ServicePriceUpdate(BaseSchema):
    """Service price update schema"""

    base_price: Decimal
    effective_date: datetime = datetime.now()


class ServiceBulkUpdate(BaseSchema):
    """Bulk service update schema"""

    service_ids: List[UUID]
    base_price: Optional[Decimal] = None
    status: Optional[ServiceStatus] = None
    tax_rate: Optional[Decimal] = None


class ServiceCategorySummary(BaseSchema):
    """Service category summary"""

    category: ServiceCategory
    total_services: int
    active_services: int
    average_price: Decimal
