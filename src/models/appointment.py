# src/models/appointment.py
import uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    DateTime,
    String,
    Enum,
    Text,
    Boolean,
    Integer,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class AppointmentStatus(str, PyEnum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"


class AppointmentType(str, PyEnum):
    CONSULTATION = "consultation"
    TREATMENT = "treatment"
    FOLLOW_UP = "follow_up"
    EMERGENCY = "emergency"
    HYGIENE = "hygiene"
    CHECKUP = "checkup"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Core appointment details
    dentist_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)

    # Timing
    appointment_date = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, default=30)
    appointment_type = Column(Enum(AppointmentType), nullable=False)

    # Status
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.SCHEDULED)
    is_urgent = Column(Boolean, default=False)

    # Appointment details
    reason = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    symptoms = Column(JSON, nullable=True)  # Store as structured data

    # Reminders and notifications
    reminder_sent = Column(Boolean, default=False)
    confirmation_sent = Column(Boolean, default=False)

    # Room and equipment
    room_id = Column(String(20), nullable=True)
    equipment_required = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="appointments")
    dentist = relationship(
        "User", back_populates="appointments", foreign_keys=[dentist_id]
    )
    patient = relationship(
        "Patient", back_populates="appointments", foreign_keys=[patient_id]
    )
    consultation = relationship(
        "Consultation", back_populates="appointment", uselist=False
    )
    treatments = relationship(
        "Treatment", back_populates="appointment", cascade="all, delete-orphan"
    )

    def __repr__(self):
        """Safe __repr__ that doesn't trigger lazy loading"""
        try:
            # Try to get patient first name without triggering lazy load
            patient_name = getattr(self, "_patient_name", None)
            if not patient_name and hasattr(self, "patient") and self.patient:
                # Only access if already loaded
                patient_name = (
                    self.patient.first_name
                    if hasattr(self.patient, "first_name")
                    else "Unknown"
                )

            # Try to get dentist last name without triggering lazy load
            dentist_name = getattr(self, "_dentist_name", None)
            if not dentist_name and hasattr(self, "dentist") and self.dentist:
                # Only access if already loaded
                dentist_name = (
                    self.dentist.last_name
                    if hasattr(self.dentist, "last_name")
                    else "Unknown"
                )

            return f"<Appointment {self.id} - {patient_name or 'Unknown'} with Dr. {dentist_name or 'Unknown'}>"
        except Exception:
            # Fallback if anything goes wrong
            return f"<Appointment {self.id}>"
