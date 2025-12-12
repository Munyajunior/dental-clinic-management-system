# src/schemas/prescription_schemas.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin
from enum import Enum


class PrescriptionStatus(str, Enum):
    ACTIVE = "active"
    DISPENSED = "dispensed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    RENEWED = "renewed"


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
    tenant_id: Optional[UUID] = None
    original_prescription_id: Optional[UUID] = None
    renewal_reason: Optional[str] = None
    renewal_notes: Optional[str] = None


class PrescriptionUpdate(BaseSchema):
    """Schema for updating a prescription"""

    medication_name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    quantity: Optional[str] = None
    refills: Optional[int] = None
    refills_remaining: Optional[int] = None
    status: Optional[PrescriptionStatus] = None


class PrescriptionRenew(BaseSchema):
    """Schema for renewing a prescription"""

    renewal_reason: str
    renewal_notes: Optional[str] = None
    adjust_original_refills: bool = True
    copy_instructions: bool = True
    new_expiration_days: Optional[int] = 30
    custom_medication_name: Optional[str] = None
    custom_dosage: Optional[str] = None
    custom_frequency: Optional[str] = None
    custom_duration: Optional[str] = None
    custom_instructions: Optional[str] = None


class PrescriptionInDB(IDMixin, TenantMixin, PrescriptionBase, TimestampMixin):
    """Prescription schema for database representation"""

    instructions: Optional[str] = None
    quantity: Optional[str] = None
    refills: int
    refills_remaining: int
    status: PrescriptionStatus
    is_dispensed: bool
    dispensed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    original_prescription_id: Optional[UUID] = None
    renewal_number: int
    renewal_chain_id: Optional[UUID] = None
    renewal_reason: Optional[str] = None
    renewal_notes: Optional[str] = None


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
    quantity: Optional[str] = None
    refills: int
    refills_remaining: int
    status: PrescriptionStatus
    is_dispensed: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    dentist_name: Optional[str] = None
    patient_name: Optional[str] = None
    original_prescription_id: Optional[UUID] = None
    renewal_number: int
    is_renewal: bool
    has_renewals: bool
    renewal_count: int


class PrescriptionDetail(PrescriptionPublic):
    """Detailed prescription schema"""

    dispensed_at: Optional[datetime] = None
    treatment_name: Optional[str] = None
    renewal_chain_id: Optional[UUID] = None
    renewal_reason: Optional[str] = None
    renewal_notes: Optional[str] = None
    original_prescription_details: Optional[Dict] = None
    renewal_history: List[Dict] = []
