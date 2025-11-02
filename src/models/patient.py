# src/models/patient.py
import base64
import uuid
from sqlalchemy import (
    Column,
    String,
    ForeignKey,
    Text,
    DateTime,
    Enum,
    Boolean,
    LargeBinary,
    Date,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class GenderEnum(str, PyEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class PatientStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DECEASED = "deceased"


class InsuranceType(str, PyEnum):
    PRIVATE = "private"
    PUBLIC = "public"
    NONE = "none"


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Personal information
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(Enum(GenderEnum), nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # Contact information
    contact_number = Column(String(20), nullable=False)
    email = Column(String(100), nullable=False, unique=True)
    address = Column(Text, nullable=False)
    emergency_contact_name = Column(String(100), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)

    # Medical information
    medical_history = Column(JSON, default=dict)  # Allergies, conditions, medications
    dental_history = Column(JSON, default=dict)  # Previous dental work, concerns
    insurance_info = Column(JSON, nullable=True)  # Insurance details

    # Status and preferences
    status = Column(Enum(PatientStatus), default=PatientStatus.ACTIVE)
    preferences = Column(JSON, default=dict)  # Communication preferences, etc.

    # Profile
    profile_picture = Column(LargeBinary, nullable=True)
    profile_picture_type = Column(String(50), nullable=True)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_visit_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="patients")
    created_by_user = relationship(
        "User", back_populates="created_patients", foreign_keys=[created_by]
    )
    updated_by_user = relationship(
        "User", back_populates="updated_patients", foreign_keys=[updated_by]
    )

    # Clinical relationships
    appointments = relationship(
        "Appointment", back_populates="patient", cascade="all, delete-orphan"
    )
    consultations = relationship(
        "Consultation", back_populates="patient", cascade="all, delete-orphan"
    )
    treatments = relationship(
        "Treatment", back_populates="patient", cascade="all, delete-orphan"
    )
    medical_records = relationship(
        "MedicalRecord", back_populates="patient", cascade="all, delete-orphan"
    )
    prescriptions = relationship(
        "Prescription", back_populates="patient", cascade="all, delete-orphan"
    )
    invoices = relationship(
        "Invoice", back_populates="patient", cascade="all, delete-orphan"
    )

    def set_profile_picture(self, image_data: bytes, content_type: str):
        self.profile_picture = image_data
        self.profile_picture_type = content_type

    def get_profile_picture_base64(self):
        if self.profile_picture and self.profile_picture_type:
            return f"data:{self.profile_picture_type};base64,{base64.b64encode(self.profile_picture).decode('utf-8')}"
        return None

    def calculate_age(self):
        from datetime import date

        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - (
                (today.month, today.day)
                < (self.date_of_birth.month, self.date_of_birth.day)
            )
        )
