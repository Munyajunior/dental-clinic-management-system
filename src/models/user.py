# src/models/user.py
import base64
import json
import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    LargeBinary,
    Enum,
    Date,
    ForeignKey,
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


class StaffRole(str, PyEnum):
    ADMIN = "admin"
    DENTIST = "dentist"
    HYGIENIST = "hygienist"
    ASSISTANT = "assistant"
    RECEPTIONIST = "receptionist"
    MANAGER = "manager"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Personal information
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    date_of_birth = Column(Date, nullable=True)
    contact_number = Column(String(20), nullable=False)
    email = Column(String(100), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)

    # Professional information
    role = Column(Enum(StaffRole), nullable=False)
    gender = Column(Enum(GenderEnum), nullable=False)
    specialization = Column(String(100), nullable=True)  # General, Orthodontics, etc.
    license_number = Column(String(50), nullable=True)
    employee_id = Column(String(50), nullable=True)

    # Work schedule and availability
    work_schedule = Column(
        JSON, nullable=True
    )  # Store as JSON: {"monday": ["09:00-17:00"], ...}
    is_available = Column(Boolean, default=True)

    # Profile and settings
    profile_picture = Column(LargeBinary, nullable=True)
    profile_picture_type = Column(String(50), nullable=True)
    settings = Column(JSON, default=dict)

    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    login_attempts = relationship("LoginAttempt", back_populates="user", cascade="all")
    # As treating dentist
    appointments = relationship(
        "Appointment", back_populates="dentist", foreign_keys="[Appointment.dentist_id]"
    )
    treatments = relationship(
        "Treatment", back_populates="dentist", foreign_keys="[Treatment.dentist_id]"
    )
    consultations = relationship(
        "Consultation",
        back_populates="dentist",
        foreign_keys="[Consultation.dentist_id]",
    )

    # As creator/updater
    created_patients = relationship(
        "Patient", back_populates="created_by_user", foreign_keys="[Patient.created_by]"
    )
    updated_patients = relationship(
        "Patient", back_populates="updated_by_user", foreign_keys="[Patient.updated_by]"
    )

    def set_profile_picture(self, image_data: bytes, content_type: str):
        """Store profile picture in the database."""
        self.profile_picture = image_data
        self.profile_picture_type = content_type

    def get_profile_picture_base64(self):
        """Get profile picture as base64 encoded string."""
        if self.profile_picture and self.profile_picture_type:
            return f"data:{self.profile_picture_type};base64,{base64.b64encode(self.profile_picture).decode('utf-8')}"
        return None

    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission based on role."""
        role_permissions = {
            StaffRole.ADMIN: ["all"],
            StaffRole.DENTIST: [
                "view_patients",
                "create_treatments",
                "manage_appointments",
            ],
            StaffRole.HYGIENIST: ["view_patients", "create_cleanings"],
            StaffRole.ASSISTANT: ["view_patients", "assist_treatments"],
            StaffRole.RECEPTIONIST: ["manage_appointments", "view_patients"],
            StaffRole.MANAGER: ["manage_users", "view_reports"],
        }
        return "all" in role_permissions.get(
            self.role, []
        ) or permission in role_permissions.get(self.role, [])
