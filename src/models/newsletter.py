# src/models/newsletter.py
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, String, Text, Integer, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from db.database import Base


class NewsletterStatus(str, PyEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"


class SubscriptionStatus(str, PyEnum):
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"


class Newsletter(Base):
    __tablename__ = "newsletters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Newsletter content
    subject = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    template_name = Column(String(100), nullable=True)

    # Status and scheduling
    status = Column(Enum(NewsletterStatus), default=NewsletterStatus.DRAFT)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Recipients
    recipient_filters = Column(JSON, nullable=True)  # Criteria for selecting recipients
    total_recipients = Column(Integer, default=0)
    total_sent = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    creator = relationship("User", foreign_keys=[created_by])
    subscriptions = relationship("NewsletterSubscription", back_populates="newsletter")


class NewsletterSubscription(Base):
    __tablename__ = "newsletter_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    newsletter_id = Column(
        UUID(as_uuid=True), ForeignKey("newsletters.id"), nullable=True
    )

    # Subscription details
    email = Column(String(100), nullable=False)
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.SUBSCRIBED)
    preferences = Column(JSON, nullable=True)  # Communication preferences

    # Tracking
    unsubscribed_at = Column(DateTime(timezone=True), nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant")
    patient = relationship("Patient")
    newsletter = relationship("Newsletter", back_populates="subscriptions")
