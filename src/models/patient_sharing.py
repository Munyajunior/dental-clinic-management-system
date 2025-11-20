# src/models/patient_sharing.py
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, Text, String, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class PatientSharing(Base):
    __tablename__ = "patient_sharing"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Sharing details
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    shared_by_dentist_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    shared_with_dentist_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Permissions
    permission_level = Column(
        String(20), nullable=False, default="view"
    )  # view, consult, modify
    is_active = Column(Boolean, default=True)

    # Expiration
    expires_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient")
    shared_by_dentist = relationship("User", foreign_keys=[shared_by_dentist_id])
    shared_with_dentist = relationship("User", foreign_keys=[shared_with_dentist_id])
