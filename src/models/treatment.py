# src/models/treatment.py
import uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    DateTime,
    Text,
    JSON,
    String,
    Numeric,
    Enum,
    Integer,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class TreatmentStatus(str, PyEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"


class Treatment(Base):
    __tablename__ = "treatments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Core relationships
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    dentist_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    consultation_id = Column(
        UUID(as_uuid=True), ForeignKey("consultations.id"), nullable=True
    )
    appointment_id = Column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True
    )

    # Treatment details
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TreatmentStatus), default=TreatmentStatus.PLANNED)
    priority = Column(String(20), default="routine")  # emergency, urgent, routine

    # Tooth/quadrant information
    teeth_involved = Column(JSON, nullable=True)  # List of tooth numbers
    quadrants = Column(JSON, nullable=True)  # UR, UL, LL, LR

    # Progress tracking
    progress_notes = Column(JSON, default=list)  # List of progress entries
    current_stage = Column(String(50), nullable=True)
    total_stages = Column(Integer, default=1)

    # Financials
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    actual_cost = Column(Numeric(10, 2), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient", back_populates="treatments")
    dentist = relationship(
        "User", back_populates="treatments", foreign_keys=[dentist_id]
    )
    consultation = relationship("Consultation", back_populates="treatments")
    appointment = relationship("Appointment", back_populates="treatments")
    treatment_items = relationship(
        "TreatmentItem", back_populates="treatment", cascade="all, delete-orphan"
    )
    prescriptions = relationship(
        "Prescription", back_populates="treatment", cascade="all, delete-orphan"
    )
