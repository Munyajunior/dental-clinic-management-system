# src/schemas/medical_record_schemas.py
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from models.medical_record import RecordType
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class MedicalRecordBase(BaseSchema):
    """Base medical record schema"""

    patient_id: UUID
    record_type: RecordType
    title: str
    description: Optional[str] = None


class MedicalRecordCreate(MedicalRecordBase):
    """Schema for creating a medical record"""

    clinical_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    file_data: Optional[str] = None  # Base64 encoded file
    file_name: Optional[str] = None
    mime_type: Optional[str] = None


class MedicalRecordUpdate(BaseSchema):
    """Schema for updating a medical record"""

    title: Optional[str] = None
    description: Optional[str] = None
    clinical_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class MedicalRecordInDB(IDMixin, TenantMixin, MedicalRecordBase, TimestampMixin):
    """Medical record schema for database representation"""

    clinical_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    record_date: datetime
    created_by: UUID


class MedicalRecordPublic(BaseSchema):
    """Public medical record schema"""

    id: UUID
    patient_id: UUID
    record_type: RecordType
    title: str
    description: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    record_date: datetime
    created_at: datetime


class MedicalRecordDetail(MedicalRecordPublic):
    """Detailed medical record schema"""

    clinical_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    file_url: Optional[str] = None  # Presigned URL for download
    created_by_name: str


class RadiographRecord(BaseSchema):
    """Radiograph-specific record schema"""

    teeth: List[str]
    view_type: str  # periapical, bitewing, panoramic, etc.
    findings: Optional[str] = None
    interpretation: Optional[str] = None


class ClinicalNote(BaseSchema):
    """Clinical note schema"""

    subjective: Optional[str] = None  # Patient's complaints
    objective: Optional[str] = None  # Clinical findings
    assessment: Optional[str] = None  # Diagnosis
    plan: Optional[str] = None  # Treatment plan
