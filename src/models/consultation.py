# src/models/consultation.py
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, Text, JSON, String, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class Consultation(Base):
    __tablename__ = "consultations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Relationships
    appointment_id = Column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    dentist_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Clinical examination
    chief_complaint = Column(Text, nullable=True)
    medical_history_review = Column(JSON, nullable=True)
    dental_history_review = Column(JSON, nullable=True)

    # Examination findings
    extraoral_findings = Column(Text, nullable=True)
    intraoral_findings = Column(Text, nullable=True)
    periodontal_assessment = Column(
        JSON, nullable=True
    )  # Pocket depths, bleeding points
    occlusion_assessment = Column(Text, nullable=True)

    # Diagnosis and plan
    diagnosis = Column(JSON, nullable=True)  # List of diagnoses
    treatment_plan = Column(JSON, nullable=True)  # Proposed treatment steps
    recommendations = Column(Text, nullable=True)

    # Fees and follow-up
    consultation_fee = Column(Numeric(10, 2), nullable=True)
    next_appointment_date = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    appointment = relationship("Appointment", back_populates="consultation")
    patient = relationship("Patient", back_populates="consultations")
    dentist = relationship(
        "User", back_populates="consultations", foreign_keys=[dentist_id]
    )
    treatments = relationship(
        "Treatment", back_populates="consultation", cascade="all, delete-orphan"
    )
