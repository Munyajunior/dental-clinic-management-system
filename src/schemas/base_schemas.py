# src/schemas/base_schemas.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


class BaseSchema(BaseModel):
    """Base schema with common configuration"""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        arbitrary_types_allowed=True,
    )


class TimestampMixin(BaseSchema):
    """Mixin for timestamps"""

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IDMixin(BaseSchema):
    """Mixin for ID field"""

    id: UUID


class TenantMixin(BaseSchema):
    """Mixin for tenant context"""

    tenant_id: UUID


class ResponseBase(BaseSchema):
    """Base response schema"""

    success: bool = True
    message: Optional[str] = None


class PaginationParams(BaseSchema):
    """Pagination parameters"""

    page: int = 1
    page_size: int = 50
    order_by: Optional[str] = None
    order_direction: str = "desc"


class PaginatedResponse(BaseSchema):
    """Paginated response schema"""

    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class BulkOperationResponse(BaseSchema):
    """Response for bulk operations"""

    success: bool
    processed: int
    failed: int
    errors: Optional[list[str]] = None
