# src/models/tenant.py
import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    Enum,
    JSON,
    Integer,
    Boolean,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base
from enum import Enum as PyEnum
from utils.logger import setup_logger
from datetime import datetime, timedelta

logger = setup_logger("TENANT")


class TenantTier(str, PyEnum):
    TRIAL = "trial"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class TenantPaymentStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    CANCELLED = "cancelled"
    PENDING = "pending"  # Waiting for payment/verification
    GRACE_PERIOD = "grace_period"  # Past due but in grace period


class TenantStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class BillingCycle(str, PyEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(50), nullable=False, unique=True)
    contact_email = Column(String(100), nullable=False)
    contact_phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)

    # Tenant Status & Tier
    tier = Column(Enum(TenantTier), default=TenantTier.TRIAL, nullable=False)
    payment_status = Column(
        Enum(TenantPaymentStatus), default=TenantPaymentStatus.PENDING, nullable=False
    )
    status = Column(Enum(TenantStatus), default=TenantStatus.ACTIVE, nullable=False)

    # Subscription & Billing
    subscription_id = Column(String(100), nullable=True)
    billing_cycle = Column(Enum(BillingCycle), default=BillingCycle.MONTHLY)
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)

    # Usage Limits
    max_users = Column(Integer, default=5)
    max_patients = Column(Integer, default=1000)
    max_storage_gb = Column(Integer, default=1)
    max_api_calls_per_month = Column(Integer, default=10000)

    # Current Usage (updated periodically)
    current_user_count = Column(Integer, default=0)
    current_patient_count = Column(Integer, default=0)
    current_storage_gb = Column(Float, default=0.0)
    current_api_calls_this_month = Column(Integer, default=0)

    # Database isolation level
    isolation_level = Column(String(20), default="shared")

    # Features and Configuration
    enabled_features = Column(JSON, default=dict)  # Feature flags
    settings = Column(JSON, default=dict)  # Tenant-specific settings
    restrictions = Column(JSON, default=dict)  # Usage restrictions

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    trial_ends_at = Column(DateTime(timezone=True))
    subscription_ends_at = Column(DateTime(timezone=True))
    billing_cycle_ends_at = Column(DateTime(timezone=True))
    grace_period_ends_at = Column(DateTime(timezone=True))

    # Audit fields
    last_billing_date = Column(DateTime(timezone=True))
    last_usage_update = Column(DateTime(timezone=True))
    activation_date = Column(DateTime(timezone=True))

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    patients = relationship(
        "Patient", back_populates="tenant", cascade="all, delete-orphan"
    )
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="tenant", cascade="all, delete-orphan"
    )
    services = relationship(
        "Service", back_populates="tenant", cascade="all, delete-orphan"
    )
    appointments = relationship(
        "Appointment", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Tenant {self.name} ({self.tier} - {self.status})>"

    @property
    def is_active(self) -> bool:
        """Check if tenant is active and not expired"""
        return self.status in [
            TenantStatus.ACTIVE,
            TenantStatus.TRIAL,
            TenantStatus.GRACE_PERIOD,
        ]

    @property
    def is_trial(self) -> bool:
        """Check if tenant is in trial period"""
        return self.status == TenantStatus.TRIAL

    @property
    def trial_days_remaining(self) -> int:
        """Calculate remaining trial days"""
        if not self.trial_ends_at or not self.is_trial:
            return 0
        remaining = self.trial_ends_at - datetime.utcnow()
        return max(0, remaining.days)

    @property
    def has_exceeded_limits(self) -> bool:
        """Check if tenant has exceeded any usage limits"""
        return (
            self.current_user_count >= self.max_users
            or self.current_patient_count >= self.max_patients
            or self.current_storage_gb >= self.max_storage_gb
            or self.current_api_calls_this_month >= self.max_api_calls_per_month
        )

    def can_add_user(self) -> bool:
        """Check if tenant can add another user"""
        return self.current_user_count < self.max_users

    def can_add_patient(self) -> bool:
        """Check if tenant can add another patient"""
        return self.current_patient_count < self.max_patients

    @classmethod
    async def create_tenant(cls, session, **kwargs):
        """Create a new tenant with proper initialization"""
        from db.database import create_tenant_config

        tenant = cls(**kwargs)

        # Set trial end date if not provided
        if not tenant.trial_ends_at and tenant.tier == TenantTier.TRIAL:
            tenant.trial_ends_at = datetime.utcnow() + timedelta(days=30)

        session.add(tenant)
        await session.flush()

        # Initialize tenant configuration
        await create_tenant_config(str(tenant.id))

        return tenant
