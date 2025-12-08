# src/schemas/appointment_schemas.py
from pydantic import field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from models.appointment import AppointmentStatus, AppointmentType
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class AppointmentBase(BaseSchema):
    """Base appointment schema"""

    dentist_id: UUID
    patient_id: UUID
    appointment_date: datetime
    duration_minutes: int = 30
    appointment_type: AppointmentType
    reason: str


class AppointmentCreate(AppointmentBase):
    """Schema for creating an appointment"""

    notes: Optional[str] = None
    symptoms: Optional[Dict[str, Any]] = None
    is_urgent: bool = False
    room_id: Optional[str] = None
    equipment_required: Optional[List[str]] = None
    tenant_id: Optional[UUID] = None

    @field_validator("appointment_date")
    @classmethod
    def validate_appointment_date(cls, v: datetime) -> datetime:
        if v < datetime.now():
            raise ValueError("Appointment date cannot be in the past")
        return v


class AppointmentUpdate(BaseSchema):
    """Schema for updating an appointment"""

    dentist_id: Optional[UUID] = None
    appointment_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    appointment_type: Optional[AppointmentType] = None
    status: Optional[AppointmentStatus] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    symptoms: Optional[Dict[str, Any]] = None
    is_urgent: Optional[bool] = None
    room_id: Optional[str] = None
    equipment_required: Optional[List[str]] = None


class AppointmentInDB(IDMixin, TenantMixin, AppointmentBase, TimestampMixin):
    """Appointment schema for database representation"""

    status: AppointmentStatus
    notes: Optional[str] = None
    symptoms: Optional[Dict[str, Any]] = None
    is_urgent: bool
    room_id: Optional[str] = None
    equipment_required: Optional[List[str]] = None
    reminder_sent: bool
    confirmation_sent: bool
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None


class AppointmentPublic(BaseSchema):
    """Public appointment schema"""

    id: UUID
    dentist_id: UUID
    patient_id: UUID
    appointment_date: datetime
    duration_minutes: int
    appointment_type: AppointmentType
    status: AppointmentStatus
    reason: str
    is_urgent: bool
    patient_name: Optional[str] = None
    dentist_name: Optional[str] = None


class AppointmentDetail(AppointmentPublic):
    """Detailed appointment schema"""

    dentist_name: str
    patient_name: str
    patient_contact: str
    notes: Optional[str] = None
    symptoms: Optional[Dict[str, Any]] = None
    room_id: Optional[str] = None
    confirmed_at: Optional[datetime] = None


class AppointmentSlot(BaseSchema):
    """Appointment slot schema"""

    start_time: datetime
    end_time: datetime
    is_available: bool
    dentist_id: UUID
    dentist_name: str


class AppointmentSearch(BaseSchema):
    """Appointment search parameters"""

    dentist_id: Optional[UUID] = None
    patient_id: Optional[UUID] = None
    status: Optional[AppointmentStatus] = None
    appointment_type: Optional[AppointmentType] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    is_urgent: Optional[bool] = None


class AppointmentBulkCreate(BaseSchema):
    """Bulk appointment creation schema"""

    appointments: List[AppointmentCreate]


class AppointmentStatusUpdate(BaseSchema):
    """Appointment status update schema"""

    status: AppointmentStatus
    cancellation_reason: Optional[str] = None


class AppointmentReminder(BaseSchema):
    """Appointment reminder schema"""

    appointment_id: UUID
    reminder_type: str  # email, sms, both
    send_at: datetime
