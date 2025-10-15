# src/models/medical_record.py
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, Text, JSON, String, Enum, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class RecordType(str, PyEnum):
    CLINICAL_NOTE = "clinical_note"
    RADIOGRAPH = "radiograph"
    PHOTOGRAPH = "photograph"
    LAB_RESULT = "lab_result"
    CONSENT_FORM = "consent_form"
    MEDICAL_HISTORY = "medical_history"


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Record details
    record_type = Column(Enum(RecordType), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # File storage (for images, documents)
    file_path = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)

    # Clinical data
    clinical_data = Column(JSON, nullable=True)
    tags = Column(JSON, nullable=True)  # For categorization

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    record_date = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient", back_populates="medical_records")
    creator = relationship("User", foreign_keys=[created_by])
