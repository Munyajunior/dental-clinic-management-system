# src/schemas/prescription_schemas.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class PrescriptionBase(BaseSchema):
    """Base prescription schema"""

    patient_id: UUID
    dentist_id: UUID
    medication_name: str
    dosage: str
    frequency: str
    duration: str
    treatment_id: Optional[UUID] = None


class PrescriptionCreate(PrescriptionBase):
    """Schema for creating a prescription"""

    instructions: Optional[str] = None
    quantity: Optional[str] = None
    refills: int = 0


class PrescriptionUpdate(BaseSchema):
    """Schema for updating a prescription"""

    medication_name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    quantity: Optional[str] = None
    refills: Optional[int] = None
    is_dispensed: Optional[bool] = None


class PrescriptionInDB(IDMixin, TenantMixin, PrescriptionBase, TimestampMixin):
    """Prescription schema for database representation"""

    instructions: Optional[str] = None
    quantity: Optional[str] = None
    refills: int
    is_dispensed: bool
    dispensed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PrescriptionPublic(BaseSchema):
    """Public prescription schema"""

    id: UUID
    patient_id: UUID
    dentist_id: UUID
    medication_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: Optional[str] = None
    is_dispensed: bool
    created_at: datetime
    expires_at: Optional[datetime] = None


class PrescriptionDetail(PrescriptionPublic):
    """Detailed prescription schema"""

    quantity: Optional[str] = None
    refills: int
    dispensed_at: Optional[datetime] = None
    dentist_name: str
    patient_name: str
    treatment_name: Optional[str] = None
