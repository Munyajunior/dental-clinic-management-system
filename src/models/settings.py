# src/models/settings.py
import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    JSON,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )

    # Settings categories
    category = Column(
        String(50), nullable=False, index=True
    )  # general, clinic, notifications, billing, security
    settings_key = Column(String(100), nullable=False, index=True)
    settings_value = Column(JSON, nullable=False)

    # Metadata
    description = Column(Text, nullable=True)
    is_encrypted = Column(Boolean, default=False)
    version = Column(String(20), default="1.0.0")

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships - use string-based references
    tenant = relationship("Tenant", back_populates="settings_entries")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])

    # Unique constraint per tenant, category, and key
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "category", "settings_key", name="uq_tenant_settings"
        ),
    )


class SettingsAudit(Base):
    __tablename__ = "settings_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    settings_id = Column(
        UUID(as_uuid=True), ForeignKey("tenant_settings.id"), nullable=False
    )

    # Change details
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=False)
    change_type = Column(String(20), nullable=False)  # created, updated, deleted
    change_reason = Column(Text, nullable=True)

    # User who made the change
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Timestamp
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    tenant = relationship("Tenant")
    settings = relationship("TenantSettings")
    changer = relationship("User", foreign_keys=[changed_by])
