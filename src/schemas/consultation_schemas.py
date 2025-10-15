# src/schemas/consultation_schemas.py
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class ConsultationBase(BaseSchema):
    """Base consultation schema"""

    patient_id: UUID
    dentist_id: UUID
    appointment_id: Optional[UUID] = None


class ConsultationCreate(ConsultationBase):
    """Schema for creating a consultation"""

    chief_complaint: Optional[str] = None
    medical_history_review: Optional[Dict[str, Any]] = None
    dental_history_review: Optional[Dict[str, Any]] = None
    extraoral_findings: Optional[str] = None
    intraoral_findings: Optional[str] = None
    periodontal_assessment: Optional[Dict[str, Any]] = None
    occlusion_assessment: Optional[str] = None
    diagnosis: Optional[List[str]] = None
    treatment_plan: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    next_appointment_date: Optional[datetime] = None


class ConsultationUpdate(BaseSchema):
    """Schema for updating a consultation"""

    chief_complaint: Optional[str] = None
    medical_history_review: Optional[Dict[str, Any]] = None
    dental_history_review: Optional[Dict[str, Any]] = None
    extraoral_findings: Optional[str] = None
    intraoral_findings: Optional[str] = None
    periodontal_assessment: Optional[Dict[str, Any]] = None
    occlusion_assessment: Optional[str] = None
    diagnosis: Optional[List[str]] = None
    treatment_plan: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    next_appointment_date: Optional[datetime] = None


class ConsultationInDB(IDMixin, TenantMixin, ConsultationBase, TimestampMixin):
    """Consultation schema for database representation"""

    chief_complaint: Optional[str] = None
    medical_history_review: Optional[Dict[str, Any]] = None
    dental_history_review: Optional[Dict[str, Any]] = None
    extraoral_findings: Optional[str] = None
    intraoral_findings: Optional[str] = None
    periodontal_assessment: Optional[Dict[str, Any]] = None
    occlusion_assessment: Optional[str] = None
    diagnosis: Optional[List[str]] = None
    treatment_plan: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    next_appointment_date: Optional[datetime] = None


class ConsultationPublic(BaseSchema):
    """Public consultation schema"""

    id: UUID
    patient_id: UUID
    dentist_id: UUID
    appointment_id: Optional[UUID] = None
    chief_complaint: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    next_appointment_date: Optional[datetime] = None
    created_at: datetime


class ConsultationDetail(ConsultationPublic):
    """Detailed consultation schema"""

    medical_history_review: Optional[Dict[str, Any]] = None
    dental_history_review: Optional[Dict[str, Any]] = None
    extraoral_findings: Optional[str] = None
    intraoral_findings: Optional[str] = None
    periodontal_assessment: Optional[Dict[str, Any]] = None
    occlusion_assessment: Optional[str] = None
    diagnosis: Optional[List[str]] = None
    treatment_plan: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[str] = None
    dentist_name: str
    patient_name: str


class PeriodontalAssessment(BaseSchema):
    """Periodontal assessment schema"""

    pocket_depths: Dict[str, int]  # tooth_number: depth_in_mm
    bleeding_points: List[str]  # tooth numbers with bleeding
    plaque_index: Optional[float] = None
    gingival_index: Optional[float] = None
    mobility: Optional[Dict[str, int]] = None  # tooth_number: mobility_grade
