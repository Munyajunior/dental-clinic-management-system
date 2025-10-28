# src/schemas/user_schemas.py
from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from uuid import UUID
from models.user import StaffRole, GenderEnum
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


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
    work_schedule: Optional[Dict[str, Any]] = None

    contact_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[GenderEnum] = None

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
    work_schedule: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None


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
    is_available: bool
    profile_picture: Optional[str] = None


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


class UserLoginResponse(BaseSchema):
    """User login response"""

    access_token: str
    token_type: str = "bearer"
    user: UserPublic
    tenant: dict


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


class UserWorkSchedule(BaseSchema):
    """User work schedule schema"""

    monday: List[str] = []  # ["09:00-17:00"]
    tuesday: List[str] = []
    wednesday: List[str] = []
    thursday: List[str] = []
    friday: List[str] = []
    saturday: List[str] = []
    sunday: List[str] = []
