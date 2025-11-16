# src/models/user.py
import base64
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
    Integer,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base
from datetime import datetime, timezone


class GenderEnum(str, PyEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class StaffRole(str, PyEnum):
    ADMIN = "admin"
    DENTIST = "dentist"
    DENTAL_THERAPIST = "dental_therapist"
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

    # Dentist-specific fields
    max_patients = Column(Integer, default=50)  # Maximum patients per dentist
    is_accepting_new_patients = Column(Boolean, default=True)
    availability_schedule = Column(JSON, nullable=True)  # Work schedule as JSON

    # System Permissions
    permissions = Column(JSON, default=dict)

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

    # Analytics fields
    login_count = Column(Integer, default=0)
    failed_login_attempts = Column(Integer, default=0)
    last_failed_login = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    login_attempts = relationship("LoginAttempt", back_populates="user", cascade="all")

    # Dentist-specific relationships
    assigned_patients = relationship(
        "Patient",
        back_populates="assigned_dentist",
        foreign_keys="[Patient.assigned_dentist_id]",
    )
    preferred_by_patients = relationship(
        "Patient",
        back_populates="preferred_dentist",
        foreign_keys="[Patient.preferred_dentist_id]",
    )

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

    def __init__(self, **kwargs):
        # Ensure work_schedule is always a dict
        if "work_schedule" not in kwargs or kwargs["work_schedule"] is None:
            kwargs["work_schedule"] = {}

        # Ensure settings is always a dict
        if "settings" not in kwargs or kwargs["settings"] is None:
            kwargs["settings"] = {}

        # Ensure permissions is always a dict
        if "permissions" not in kwargs or kwargs["permissions"] is None:
            kwargs["permissions"] = {}

        # Initialize required settings fields if not present
        settings = kwargs["settings"]
        if "password_changed_at" not in settings:
            settings["password_changed_at"] = datetime.now(timezone.utc).isoformat()
        if "login_count" not in settings:
            settings["login_count"] = 0
        if "temporary_password" not in settings:
            settings["temporary_password"] = True  # Default for new users

        # Initialize dentist-specific fields
        if kwargs.get("role") == StaffRole.DENTIST:
            if "max_patients" not in kwargs:
                kwargs["max_patients"] = 50
            if "is_accepting_new_patients" not in kwargs:
                kwargs["is_accepting_new_patients"] = True
            if (
                "availability_schedule" not in kwargs
                or kwargs["availability_schedule"] is None
            ):
                kwargs["availability_schedule"] = {}

        kwargs["settings"] = settings
        super().__init__(**kwargs)

    @property
    def full_name(self) -> str:
        """Get user's full name"""
        return f"{self.first_name} {self.last_name}"

    @property
    def requires_password_reset(self) -> bool:
        """Safe property to check if user requires password reset"""
        try:
            settings = self.settings or {}
            return any(
                [
                    settings.get("force_password_reset"),
                    settings.get("password_reset_required"),
                    settings.get("temporary_password"),
                    self.last_login_at is None,  # First login
                ]
            )
        except Exception:
            return False  # Safe fallback

    @property
    def current_patient_count(self) -> int:
        """Get current number of assigned patients"""
        return (
            len([p for p in self.assigned_patients if p.status == "active"])
            if self.assigned_patients
            else 0
        )

    @property
    def workload_percentage(self) -> float:
        """Calculate current workload percentage"""
        if self.max_patients <= 0:
            return 0.0
        return (self.current_patient_count / self.max_patients) * 100

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
                "assign_patients",
                "manage_own_patients",
            ],
            StaffRole.HYGIENIST: ["view_patients", "create_cleanings"],
            StaffRole.ASSISTANT: ["view_patients", "assist_treatments"],
            StaffRole.RECEPTIONIST: [
                "manage_appointments",
                "view_patients",
                "assign_patients",
            ],
            StaffRole.MANAGER: ["manage_users", "view_reports", "assign_patients"],
        }
        return "all" in role_permissions.get(
            self.role, []
        ) or permission in role_permissions.get(self.role, [])
