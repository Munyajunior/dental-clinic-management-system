# src/models/service.py
import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Numeric,
    Boolean,
    Integer,
    ForeignKey,
    Enum,
    JSON,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class ServiceCategory(str, PyEnum):
    CONSULTATION = "consultation"
    PREVENTIVE = "preventive"
    RESTORATIVE = "restorative"
    ENDODONTICS = "endodontics"
    PERIODONTICS = "periodontics"
    PROSTHODONTICS = "prosthodontics"
    ORTHODONTICS = "orthodontics"
    ORAL_SURGERY = "oral_surgery"
    COSMETIC = "cosmetic"
    OTHER = "other"


class ServiceStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Service(Base):
    __tablename__ = "services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Service identification
    code = Column(String(20), nullable=False)  # Unique within tenant
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Enum(ServiceCategory), nullable=False)

    # Pricing
    base_price = Column(Numeric(10, 2), nullable=False)
    duration_minutes = Column(Integer, default=30)  # Estimated duration

    # Status and metadata
    status = Column(Enum(ServiceStatus), default=ServiceStatus.ACTIVE)
    is_taxable = Column(Boolean, default=True)
    tax_rate = Column(Numeric(5, 2), default=0.0)

    # Additional details
    requirements = Column(JSON, nullable=True)  # Any prerequisites
    materials = Column(JSON, nullable=True)  # Required materials

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", back_populates="services")
    treatment_items = relationship("TreatmentItem", back_populates="service")

    # Ensure code is unique per tenant
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_service_code"),
    )
