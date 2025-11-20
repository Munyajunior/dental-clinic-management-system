from pydantic import BaseModel
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class PatientSharingBase(BaseSchema):
    """Base patient sharing schema"""

    patient_id: UUID
    shared_with_dentist_id: UUID
    permission_level: str  # 'view', 'consult', 'modify'
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class PatientSharingCreate(PatientSharingBase):
    """Schema for creating patient sharing"""

    pass


class PatientSharingUpdate(BaseSchema):
    """Schema for updating patient sharing"""

    permission_level: Optional[str] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class PatientSharingInDB(IDMixin, TenantMixin, PatientSharingBase, TimestampMixin):
    """Patient sharing schema for database representation"""

    shared_by_dentist_id: UUID
    is_active: bool = True


class PatientSharingPublic(BaseSchema):
    """Public patient sharing schema"""

    id: UUID
    patient_id: UUID
    patient_name: str
    shared_with_dentist_id: UUID
    shared_with_dentist_name: str
    shared_by_dentist_name: str
    permission_level: str
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
