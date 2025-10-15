# src/schemas/treatment_schemas.py
from pydantic import field_validator
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


class TreatmentCreate(TreatmentBase):
    """Schema for creating a treatment"""

    priority: str = "routine"
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    estimated_cost: Optional[Decimal] = None
    total_stages: int = 1

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid_priorities = ["emergency", "urgent", "routine"]
        if v not in valid_priorities:
            raise ValueError(f'Priority must be one of: {", ".join(valid_priorities)}')
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
    current_stage: Optional[str] = None
    total_stages: int
    started_at: Optional[datetime] = None


class TreatmentDetail(TreatmentPublic):
    """Detailed treatment schema"""

    description: Optional[str] = None
    teeth_involved: Optional[List[str]] = None
    quadrants: Optional[List[str]] = None
    progress_notes: List[Dict[str, Any]]
    actual_cost: Optional[Decimal] = None
    completed_at: Optional[datetime] = None
    dentist_name: str
    patient_name: str


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

    pass


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
