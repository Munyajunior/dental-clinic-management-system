# src/models/prescription.py
import uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    DateTime,
    Text,
    String,
    Integer,
    Boolean,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class PrescriptionStatus(str, PyEnum):
    ACTIVE = "active"
    DISPENSED = "dispensed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"  # For original prescriptions that have been renewed
    RENEWED = "renewed"  # Mark original as renewed when creating new


class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    dentist_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    treatment_id = Column(
        UUID(as_uuid=True), ForeignKey("treatments.id"), nullable=True
    )

    # Renewal tracking
    original_prescription_id = Column(
        UUID(as_uuid=True), ForeignKey("prescriptions.id"), nullable=True
    )
    renewal_number = Column(Integer, default=0)  # 0 = original, 1 = first renewal, etc.
    renewal_chain_id = Column(
        UUID(as_uuid=True), nullable=True
    )  # Same for all in chain
    renewal_reason = Column(String(500), nullable=True)
    renewal_notes = Column(Text, nullable=True)

    # Prescription details
    medication_name = Column(String(100), nullable=False)
    dosage = Column(String(50), nullable=False)
    frequency = Column(String(50), nullable=False)
    duration = Column(String(50), nullable=False)  # e.g., "7 days"
    instructions = Column(Text, nullable=True)

    # Additional information
    quantity = Column(String(50), nullable=True)
    refills = Column(Integer, default=0)
    refills_remaining = Column(Integer, default=0)

    # Status
    status = Column(
        Enum(PrescriptionStatus), default=PrescriptionStatus.ACTIVE, nullable=False
    )
    is_dispensed = Column(Boolean, default=False)
    dispensed_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient", back_populates="prescriptions")
    dentist = relationship("User", foreign_keys=[dentist_id])
    treatment = relationship("Treatment", back_populates="prescriptions")

    # Renewal relationships
    original_prescription = relationship(
        "Prescription",
        remote_side=[id],
        backref="renewals",
        foreign_keys=[original_prescription_id],
    )
