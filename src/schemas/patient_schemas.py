# src/schemas/patient_schemas.py
from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from models.patient import PatientStatus, GenderEnum, AssignmentReason
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class PatientBase(BaseSchema):
    """Base patient schema"""

    first_name: str
    last_name: str
    date_of_birth: date
    gender: GenderEnum
    contact_number: str
    email: EmailStr
    address: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientCreate(PatientBase):
    """Schema for creating a patient"""

    tenant_id: Optional[UUID] = None
    password: Optional[str] = None
    medical_history: Optional[Dict[str, Any]] = None
    dental_history: Optional[Dict[str, Any]] = None
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None

    # Dentist assignment fields
    assigned_dentist_id: Optional[UUID] = None
    assignment_reason: Optional[AssignmentReason] = None
    preferred_dentist_id: Optional[UUID] = None

    @field_validator("password", mode="before")
    @classmethod
    def set_default_password(cls, v: Optional[str], values) -> str:
        if v is None:
            # Use email as default password if not provided
            email = values.data.get("email", "")
            return email
        return v


class PatientUpdate(BaseSchema):
    """Schema for updating a patient"""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_number: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    medical_history: Optional[Dict[str, Any]] = None
    dental_history: Optional[Dict[str, Any]] = None
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    status: Optional[PatientStatus] = None

    # Dentist assignment fields
    assigned_dentist_id: Optional[UUID] = None
    assignment_reason: Optional[AssignmentReason] = None
    preferred_dentist_id: Optional[UUID] = None
    dentist_assignment_date: Optional[datetime] = None


class PatientInDB(IDMixin, TenantMixin, PatientBase, TimestampMixin):
    """Patient schema for database representation"""

    medical_history: Dict[str, Any]
    dental_history: Dict[str, Any]
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Dict[str, Any]
    status: PatientStatus
    last_visit_at: Optional[datetime] = None

    # Dentist assignment fields
    assigned_dentist_id: Optional[UUID] = None
    assignment_reason: Optional[AssignmentReason] = None
    dentist_assignment_date: Optional[datetime] = None
    preferred_dentist_id: Optional[UUID] = None


class PatientPublic(BaseSchema):
    """Public patient schema (for listing)"""

    id: UUID
    first_name: str
    last_name: str
    email: EmailStr
    contact_number: str
    date_of_birth: date
    gender: GenderEnum
    status: PatientStatus
    age: Optional[int] = None

    # Dentist assignment info
    assigned_dentist_id: Optional[UUID] = None
    assigned_dentist_name: Optional[str] = None
    assignment_reason: Optional[str] = None


class PatientDetail(PatientPublic):
    """Detailed patient schema"""

    address: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    medical_history: Dict[str, Any]
    dental_history: Dict[str, Any]
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Dict[str, Any]
    last_visit_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Detailed dentist assignment info
    assigned_dentist_id: Optional[UUID] = None
    assigned_dentist_name: Optional[str] = None
    assigned_dentist_specialization: Optional[str] = None
    assignment_reason: Optional[str] = None
    dentist_assignment_date: Optional[datetime] = None
    preferred_dentist_id: Optional[UUID] = None
    preferred_dentist_name: Optional[str] = None


class PatientSearch(BaseSchema):
    """Patient search schema"""

    query: Optional[str] = None
    status: Optional[PatientStatus] = None
    gender: Optional[GenderEnum] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    assigned_dentist_id: Optional[UUID] = None


class DentistAssignment(BaseSchema):
    """Schema for assigning dentist to patient"""

    patient_id: UUID
    dentist_id: UUID
    assignment_reason: AssignmentReason
    notes: Optional[str] = None


class DentistReassignment(BaseSchema):
    """Schema for reassigning patient to different dentist"""

    patient_id: UUID
    new_dentist_id: UUID
    assignment_reason: AssignmentReason
    notes: Optional[str] = None


class PatientAssignmentResponse(BaseSchema):
    """Response schema for patient assignment operations"""

    success: bool
    message: str
    patient_id: UUID
    dentist_id: UUID
    assignment_reason: str
    assignment_date: datetime


class DentistWorkload(BaseSchema):
    """Dentist workload information"""

    dentist_id: UUID
    dentist_name: str
    current_patient_count: int
    max_patients: int
    workload_percentage: float
    is_accepting_new_patients: bool
    specialization: Optional[str] = None


class PatientStats(BaseSchema):
    """Patient statistics"""

    total_patients: int
    active_patients: int
    new_patients_this_month: int
    patients_with_upcoming_appointments: int
