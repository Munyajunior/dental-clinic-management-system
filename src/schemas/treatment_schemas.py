# src/schemas/treatment_schemas.py
from pydantic import field_validator, ConfigDict
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from models.treatment import TreatmentStatus
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class TreatmentBase(BaseSchema):
    """Base treatment schema"""

    patient_id: UUID
    dentist_id: UUID
    name: str
    description: Optional[str] = None
    consultation_id: Optional[UUID] = None
    appointment_id: Optional[UUID] = None


class TreatmentItemCreateRequest(BaseSchema):
    """Schema for creating treatment items in requests"""

    service_id: UUID
    quantity: int = 1
    unit_price: Optional[Decimal] = None
    tooth_number: Optional[str] = None
    surface: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = "planned"
    tenant_id: Optional[UUID] = None


class TreatmentCreate(TreatmentBase):
    """Schema for creating a treatment"""

    priority: str = "routine"
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    estimated_cost: Optional[Decimal] = None
    total_stages: int = 1
    tenant_id: Optional[UUID] = None
    treatment_items: List[TreatmentItemCreateRequest] = []
    estimated_completion_date: Optional[datetime] = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid_priorities = ["emergency", "urgent", "routine"]
        if v not in valid_priorities:
            raise ValueError(f'Priority must be one of: {", ".join(valid_priorities)}')
        return v

    @field_validator("treatment_items")
    @classmethod
    def validate_treatment_items(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate treatment items structure"""
        for item in v:
            if "service_id" not in item:
                raise ValueError("Each treatment item must have a service_id")
            if "quantity" in item and item["quantity"] < 1:
                raise ValueError("Quantity must be at least 1")
        return v


class TreatmentUpdate(BaseSchema):
    """Schema for updating a treatment"""

    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TreatmentStatus] = None
    priority: Optional[str] = None
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    current_stage: Optional[str] = None
    total_stages: Optional[int] = None
    estimated_cost: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    progress_notes: Optional[List[Dict[str, Any]]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TreatmentInDB(IDMixin, TenantMixin, TreatmentBase, TimestampMixin):
    """Treatment schema for database representation"""

    status: TreatmentStatus
    priority: str
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    progress_notes: List[Dict[str, Any]]
    current_stage: Optional[str] = None
    total_stages: int
    estimated_cost: Optional[Decimal] = None
    estimated_completion_date: Optional[datetime] = None
    actual_cost: Optional[Decimal] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TreatmentPublic(BaseSchema):
    """Public treatment schema"""

    id: UUID
    patient_id: UUID
    dentist_id: UUID
    name: str
    status: TreatmentStatus
    priority: str
    estimated_cost: Optional[Decimal] = None
    estimated_completion_date: Optional[datetime] = None
    current_stage: Optional[str] = None
    total_stages: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    patient_name: Optional[str] = None
    dentist_name: Optional[str] = None
    created_at: Optional[datetime] = None


class TreatmentDetail(TreatmentPublic):
    """Detailed treatment schema"""

    description: Optional[str] = None
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    progress_notes: List[Dict[str, Any]]
    actual_cost: Optional[Decimal] = None
    consultation_id: Optional[UUID] = None
    appointment_id: Optional[UUID] = None
    updated_at: Optional[datetime] = None


class TreatmentProgressNote(BaseSchema):
    """Treatment progress note schema"""

    stage: str
    notes: str
    procedures_performed: List[str]
    materials_used: List[str]
    complications: Optional[str] = None
    next_steps: Optional[str] = None
    recorded_by: UUID
    recorded_at: datetime = datetime.now()


class TreatmentItemBase(BaseSchema):
    """Base treatment item schema"""

    service_id: UUID
    quantity: int = 1
    tooth_number: Optional[str] = None
    surface: Optional[str] = None
    notes: Optional[str] = None


class TreatmentItemCreate(TreatmentItemBase):
    """Schema for creating a treatment item"""

    unit_price: Optional[Decimal] = (
        None  # Make optional, will use service price if not provided
    )
    status: Optional[str] = "planned"

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        if v > 100:
            raise ValueError("Quantity cannot exceed 100")
        return v

    @field_validator("tooth_number")
    @classmethod
    def validate_tooth_number(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[1-8][1-5]?$|^[1-3][0-2]?$", v):
            raise ValueError(
                "Invalid tooth number format. Use FDI notation (e.g., 11, 12)"
            )
        return v


class TreatmentItemInDB(IDMixin, TreatmentItemBase, TimestampMixin):
    """Treatment item schema for database representation"""

    treatment_id: UUID
    unit_price: Decimal
    status: str
    completed_at: Optional[datetime] = None


class TreatmentItemPublic(BaseSchema):
    """Public treatment item schema"""

    id: UUID
    treatment_id: UUID
    service_id: UUID
    service_name: str
    service_code: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    status: str
    tooth_number: Optional[str] = None
    surface: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TreatmentSearch(BaseSchema):
    """Schema for treatment search"""

    query: str
    skip: int = 0
    limit: int = 50


class TreatmentBulkUpdate(BaseSchema):
    """Schema for bulk treatment updates"""

    updates: List[Dict[str, Any]]


class TreatmentExport(BaseSchema):
    """Schema for treatment export"""

    format: str = "csv"
    filters: Optional[Dict[str, Any]] = None


class TreatmentAnalytics(BaseSchema):
    """Schema for treatment analytics"""

    total_treatments: int
    completed_treatments: int
    in_progress_treatments: int
    planned_treatments: int
    cancelled_treatments: int
    average_completion_time: Optional[float] = None
    revenue_total: Decimal
    revenue_by_status: Dict[str, Decimal]
    treatments_by_month: Dict[str, int]
    top_services: List[Dict[str, Any]]


class TreatmentTemplate(BaseSchema):
    """Schema for treatment templates"""

    id: UUID
    name: str
    description: Optional[str] = None
    category: str
    treatment_items: List[Dict[str, Any]]
    estimated_cost: Decimal
    estimated_duration: int  # in minutes
    is_active: bool = True
    created_by: UUID
    created_at: datetime


class TreatmentStats(BaseSchema):
    """Schema for treatment statistics"""

    total_count: int
    by_status: Dict[str, int]
    by_priority: Dict[str, int]
    average_cost: Decimal
    completion_rate: float
    recent_treatments: int


class TreatmentTemplateItemBase(BaseSchema):
    """Base schema for treatment template items"""

    service_id: UUID
    quantity: int = 1
    tooth_number: Optional[str] = None
    surface: Optional[str] = None
    notes: Optional[str] = None
    order_index: int = 0


class TreatmentTemplateItemCreate(TreatmentTemplateItemBase):
    """Schema for creating treatment template items"""

    pass


class TreatmentTemplateItemPublic(TreatmentTemplateItemBase):
    """Public schema for treatment template items"""

    id: UUID
    template_id: UUID
    service_name: Optional[str] = None
    service_code: Optional[str] = None
    unit_price: Optional[Decimal] = None


class TreatmentTemplateBase(BaseSchema):
    """Base schema for treatment templates"""

    name: str
    description: Optional[str] = None
    category: str
    estimated_cost: Optional[Decimal] = None
    estimated_duration: Optional[int] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v.strip()) < 2:
            raise ValueError("Template name must be at least 2 characters long")
        if len(v) > 200:
            raise ValueError("Template name cannot exceed 200 characters")
        return v.strip()

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if not v or len(v.strip()) < 2:
            raise ValueError("Category must be at least 2 characters long")
        return v.strip()


class TreatmentTemplateCreate(TreatmentTemplateBase):
    """Schema for creating treatment templates"""

    template_items: List[TreatmentTemplateItemCreate] = []


class TreatmentTemplateUpdate(BaseSchema):
    """Schema for updating treatment templates"""

    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    estimated_duration: Optional[int] = None
    is_active: Optional[bool] = None
    template_items: Optional[List[TreatmentTemplateItemCreate]] = None


class TreatmentTemplateT(TreatmentTemplateBase):
    """Complete treatment template schema"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    template_items: List[TreatmentTemplateItemPublic] = []

    # Computed fields
    created_by_name: Optional[str] = None
    items_count: Optional[int] = None


class TreatmentTemplateSearch(BaseSchema):
    """Schema for template search"""

    query: str
    category: Optional[str] = None
    skip: int = 0
    limit: int = 50


class TreatmentTemplateExport(BaseSchema):
    """Schema for template export"""

    format: str = "json"
    category: Optional[str] = None
