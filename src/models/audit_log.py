# src/models/audit_log.py
import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, Enum, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class AuditAction(str, PyEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DISPENSED = "dispensed"
    RENEWED = "renewed"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"
    VIEWED = "viewed"
    PRINTED = "printed"
    EXPORTED = "exported"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    action = Column(Enum(AuditAction), nullable=False)
    entity_type = Column(String(50), nullable=False)  # e.g., "prescription", "patient"
    entity_id = Column(UUID(as_uuid=True), nullable=False)

    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Supports IPv6
    user_agent = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Index for performance
    __table_args__ = (
        Index("ix_audit_logs_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_user_id", "user_id"),
    )
