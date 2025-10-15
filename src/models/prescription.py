# src/models/prescription.py
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, Text, String, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    dentist_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    treatment_id = Column(
        UUID(as_uuid=True), ForeignKey("treatments.id"), nullable=True
    )

    # Prescription details
    medication_name = Column(String(100), nullable=False)
    dosage = Column(String(50), nullable=False)
    frequency = Column(String(50), nullable=False)
    duration = Column(String(50), nullable=False)  # e.g., "7 days"
    instructions = Column(Text, nullable=True)

    # Additional information
    quantity = Column(String(50), nullable=True)
    refills = Column(Integer, default=0)

    # Status
    is_dispensed = Column(Boolean, default=False)
    dispensed_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient", back_populates="prescriptions")
    dentist = relationship("User", foreign_keys=[dentist_id])
    treatment = relationship("Treatment", back_populates="prescriptions")
