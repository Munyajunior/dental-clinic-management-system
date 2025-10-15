# src/schemas/patient_schemas.py
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from models.patient import PatientStatus, GenderEnum, InsuranceType
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class PatientBase(BaseSchema):
    """Base patient schema"""

    first_name: str
    last_name: str
    date_of_birth: date
    gender: GenderEnum
    contact_number: str
    email: Optional[EmailStr] = None
    address: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientCreate(PatientBase):
    """Schema for creating a patient"""

    medical_history: Optional[Dict[str, Any]] = None
    dental_history: Optional[Dict[str, Any]] = None
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    password: Optional[str] = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("Date of birth cannot be in the future")
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


class PatientInDB(IDMixin, TenantMixin, PatientBase, TimestampMixin):
    """Patient schema for database representation"""

    status: PatientStatus
    medical_history: Dict[str, Any]
    dental_history: Dict[str, Any]
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Dict[str, Any]
    profile_picture: Optional[str] = None
    last_visit_at: Optional[datetime] = None
    created_by: UUID
    updated_by: Optional[UUID] = None


class PatientPublic(BaseSchema):
    """Public patient schema"""

    id: UUID
    first_name: str
    last_name: str
    date_of_birth: date
    gender: GenderEnum
    contact_number: str
    email: Optional[EmailStr] = None
    status: PatientStatus
    last_visit_at: Optional[datetime] = None
    profile_picture: Optional[str] = None


class PatientDetail(PatientPublic):
    """Detailed patient schema"""

    address: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    medical_history: Dict[str, Any]
    dental_history: Dict[str, Any]
    insurance_info: Optional[Dict[str, Any]] = None
    preferences: Dict[str, Any]
    age: int


class PatientMedicalHistory(BaseSchema):
    """Patient medical history update schema"""

    allergies: List[str] = []
    medications: List[str] = []
    conditions: List[str] = []
    surgeries: List[str] = []
    notes: Optional[str] = None


class PatientDentalHistory(BaseSchema):
    """Patient dental history update schema"""

    previous_dental_work: List[str] = []
    concerns: List[str] = []
    habits: List[str] = []  # smoking, grinding, etc.
    notes: Optional[str] = None


class PatientInsurance(BaseSchema):
    """Patient insurance information"""

    provider: str
    policy_number: str
    group_number: Optional[str] = None
    type: InsuranceType
    verification_date: Optional[date] = None
    notes: Optional[str] = None


class PatientSearch(BaseSchema):
    """Patient search parameters"""

    query: Optional[str] = None
    status: Optional[PatientStatus] = None
    gender: Optional[GenderEnum] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None


class PatientStats(BaseSchema):
    """Patient statistics"""

    total_patients: int
    active_patients: int
    new_patients_this_month: int
    patients_with_upcoming_appointments: int
