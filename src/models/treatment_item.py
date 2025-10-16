# src/models/treatment_item.py
import uuid
from sqlalchemy import (
    Column,
    ForeignKey,
    Numeric,
    Integer,
    Text,
    Enum,
    String,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class TreatmentItemStatus(str, PyEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TreatmentItem(Base):
    __tablename__ = "treatment_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    treatment_id = Column(
        UUID(as_uuid=True), ForeignKey("treatments.id"), nullable=False
    )
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=False)

    # Item details
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False)
    status = Column(Enum(TreatmentItemStatus), default=TreatmentItemStatus.PLANNED)

    # Tooth specific
    tooth_number = Column(String(10), nullable=True)  # FDI notation: 11, 12, etc.
    surface = Column(String(10), nullable=True)  # O, B, L, M, D

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    treatment = relationship("Treatment", back_populates="treatment_items")
    service = relationship("Service", back_populates="treatment_items")
    tenant = relationship("Tenant")

    @property
    def total_price(self):
        return self.quantity * self.unit_price
