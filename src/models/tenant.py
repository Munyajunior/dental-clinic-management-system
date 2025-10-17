# src/models/tenant.py
import uuid
from sqlalchemy import Column, String, DateTime, Text, Enum, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base
from enum import Enum as PyEnum
from utils.logger import setup_logger

logger = setup_logger("TENANT")


class TenantTier(str, PyEnum):
    TRIAL = "trial"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class TenantStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    CANCELLED = "cancelled"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(50), nullable=False, unique=True)
    contact_email = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    tier = Column(Enum(TenantTier), default=TenantTier.BASIC, nullable=False)
    status = Column(Enum(TenantStatus), default=TenantStatus.TRIAL, nullable=False)

    # Subscription details
    subscription_id = Column(String(100), nullable=True)
    billing_cycle = Column(String(20), default="monthly")
    max_users = Column(Integer, default=5)
    max_patients = Column(Integer, default=1000)

    # Database isolation level
    isolation_level = Column(String(20), default="shared")

    # Settings and configuration
    settings = Column(JSON, default=dict)
    features = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    trial_ends_at = Column(DateTime(timezone=True))
    subscription_ends_at = Column(DateTime(timezone=True))

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    patients = relationship(
        "Patient", back_populates="tenant", cascade="all, delete-orphan"
    )
    services = relationship(
        "Service", back_populates="tenant", cascade="all, delete-orphan"
    )
    appointments = relationship(
        "Appointment", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Tenant {self.name} ({self.tier})>"

    @classmethod
    async def create_tenant(cls, session, **kwargs):
        """Create a new tenant with proper initialization"""
        from db.database import create_tenant_config

        tenant = cls(**kwargs)
        session.add(tenant)
        await session.flush()  # Get the ID without committing

        # Initialize tenant configuration
        await create_tenant_config(str(tenant.id))

        return tenant
