# src/schemas/user_schemas.py
from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from models.user import StaffRole, GenderEnum
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class UserWorkSchedule(BaseSchema):
    """User work schedule schema"""

    monday: List[str] = []  # ["09:00-17:00"]
    tuesday: List[str] = []
    wednesday: List[str] = []
    thursday: List[str] = []
    friday: List[str] = []
    saturday: List[str] = []
    sunday: List[str] = []


class UserBase(BaseSchema):
    """Base user schema"""

    first_name: str
    last_name: str
    email: EmailStr
    contact_number: str
    date_of_birth: Optional[date] = None
    gender: GenderEnum
    role: StaffRole
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    employee_id: Optional[str] = None


class UserCreate(UserBase):
    """Schema for creating a user"""

    password: str
    is_active: bool = True
    work_schedule: Optional[UserWorkSchedule] = None
    permissions: Dict[str, Any]
    contact_number: Optional[str] = None
    date_of_birth: Optional[date] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @field_validator("contact_number", mode="before")
    @classmethod
    def set_default_contact_number(cls, v: Optional[str]) -> str:
        return v or ""  # Ensure empty string instead of None

    @field_validator("gender", mode="before")
    @classmethod
    def set_default_gender(cls, v: Optional[GenderEnum]) -> GenderEnum:
        return v or GenderEnum.OTHER


class UserUpdate(BaseSchema):
    """Schema for updating a user"""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[GenderEnum] = None
    role: Optional[StaffRole] = None
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    employee_id: Optional[str] = None
    is_active: Optional[bool] = None
    is_available: Optional[bool] = None
    work_schedule: Optional[UserWorkSchedule] = None
    settings: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None


class UserInDB(IDMixin, TenantMixin, UserBase, TimestampMixin):
    """User schema for database representation"""

    is_active: bool
    is_verified: bool
    is_available: bool
    work_schedule: Optional[Dict[str, Any]] = None
    settings: Dict[str, Any]
    last_login_at: Optional[datetime] = None
    profile_picture: Optional[str] = None  # Base64 encoded


class UserPublic(BaseSchema):
    """Public user schema (for responses)"""

    id: UUID
    first_name: str
    last_name: str
    email: EmailStr
    contact_number: str
    role: StaffRole
    specialization: Optional[str] = None
    is_active: bool
    is_verified: bool
    is_available: bool
    work_schedule: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    permissions: Dict[str, Any] = {}
    last_login_at: Optional[datetime] = None
    profile_picture: Optional[str] = None

    @classmethod
    def from_orm_safe(cls, user: Any) -> "UserPublic":
        """Safe conversion from ORM model to UserPublic"""
        # Handle work_schedule - ensure it's always a dict
        work_schedule = getattr(user, "work_schedule", None)
        if work_schedule is None:
            work_schedule = {}
        elif isinstance(work_schedule, str):
            # Handle case where it might be stored as JSON string
            try:
                import json

                work_schedule = json.loads(work_schedule)
            except:
                work_schedule = {}

        # Handle settings - ensure it's always a dict
        settings = getattr(user, "settings", None)
        if settings is None:
            settings = {}
        elif isinstance(settings, str):
            try:
                import json

                settings = json.loads(settings)
            except:
                settings = {}

        # Handle permissions - ensure it's always a dict
        permissions = getattr(user, "permissions", None)
        if permissions is None:
            permissions = {}
        elif isinstance(permissions, str):
            try:
                import json

                permissions = json.loads(permissions)
            except:
                permissions = {}

        return cls(
            id=getattr(user, "id"),
            first_name=getattr(user, "first_name", ""),
            last_name=getattr(user, "last_name", ""),
            email=getattr(user, "email"),
            contact_number=getattr(user, "contact_number", ""),
            role=getattr(user, "role"),
            specialization=getattr(user, "specialization", None),
            is_active=getattr(user, "is_active", True),
            is_verified=getattr(user, "is_verified", False),
            is_available=getattr(user, "is_available", True),
            work_schedule=work_schedule,
            settings=settings,
            permissions=permissions,
            last_login_at=getattr(user, "last_login_at", None),
            profile_picture=(
                user.get_profile_picture_base64()
                if hasattr(user, "get_profile_picture_base64")
                else None
            ),
        )


class UserLogin(BaseSchema):
    """User login schema"""

    email: EmailStr
    password: str
    tenant_slug: Optional[str] = None

    @field_validator("tenant_slug")
    @classmethod
    def validate_tenant_slug(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Tenant slug cannot be empty")
        return v


class UserSearch(BaseSchema):
    """User search parameters with flexible boolean handling"""

    query: Optional[str] = None
    role: Optional[StaffRole] = None
    is_active: Optional[Any] = None  # Allow any type for flexible boolean handling

    @field_validator("is_active", mode="before")
    @classmethod
    def validate_is_active(cls, v):
        """Flexible boolean validation"""
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            if v.lower() in ["true", "1", "yes"]:
                return True
            elif v.lower() in ["false", "0", "no"]:
                return False
        # Return as is for the service to handle
        return v


class UserLoginResponse(BaseSchema):
    """Enhanced user login response with session info"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserPublic"
    tenant: Optional[Dict[str, Any]] = None
    session_id: str
    password_reset_required: bool = False


class UserPasswordChange(BaseSchema):
    """User password change schema"""

    current_password: str
    new_password: str


class UserProfileUpdate(BaseSchema):
    """User profile update schema"""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    contact_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    specialization: Optional[str] = None
    license_number: Optional[str] = None


class UserAvailability(BaseSchema):
    """User availability schema"""

    user_id: UUID
    is_available: bool
    available_from: Optional[datetime] = None
    available_until: Optional[datetime] = None
    reason: Optional[str] = None


class TokenRefresh(BaseSchema):
    """Token refresh request schema"""

    refresh_token: str
