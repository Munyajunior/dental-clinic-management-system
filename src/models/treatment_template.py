# src/models/treatment_template.py
import uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    DateTime,
    Text,
    JSON,
    String,
    Numeric,
    Integer,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class TreatmentTemplate(Base):
    __tablename__ = "treatment_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Template details
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(
        String(100), nullable=False
    )  # e.g., "Restorative", "Preventive", "Cosmetic"

    # Financial and timing estimates
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    estimated_duration = Column(Integer, nullable=True)  # in minutes

    # Status
    is_active = Column(Boolean, default=True)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    created_by_user = relationship("User", foreign_keys=[created_by])
    template_items = relationship(
        "TreatmentTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TreatmentTemplateItem.order_index",
    )


class TreatmentTemplateItem(Base):
    __tablename__ = "treatment_template_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(
        UUID(as_uuid=True), ForeignKey("treatment_templates.id"), nullable=False
    )
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=False)

    # Item details
    quantity = Column(Integer, default=1)
    tooth_number = Column(String(10), nullable=True)  # FDI notation
    surface = Column(String(10), nullable=True)  # O, B, L, M, D
    notes = Column(Text, nullable=True)
    order_index = Column(Integer, default=0)  # For ordering items in template

    # Relationships
    template = relationship("TreatmentTemplate", back_populates="template_items")
    service = relationship("Service")
