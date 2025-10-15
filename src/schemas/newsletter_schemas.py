# src/schemas/newsletter_schemas.py
from pydantic import EmailStr
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from models.newsletter import NewsletterStatus, SubscriptionStatus
from .base_schemas import BaseSchema, TimestampMixin, IDMixin, TenantMixin


class NewsletterBase(BaseSchema):
    """Base newsletter schema"""

    subject: str
    content: str


class NewsletterCreate(NewsletterBase):
    """Schema for creating a newsletter"""

    template_name: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    recipient_filters: Optional[Dict[str, Any]] = None


class NewsletterUpdate(BaseSchema):
    """Schema for updating a newsletter"""

    subject: Optional[str] = None
    content: Optional[str] = None
    template_name: Optional[str] = None
    status: Optional[NewsletterStatus] = None
    scheduled_for: Optional[datetime] = None
    recipient_filters: Optional[Dict[str, Any]] = None


class NewsletterInDB(IDMixin, TenantMixin, NewsletterBase, TimestampMixin):
    """Newsletter schema for database representation"""

    template_name: Optional[str] = None
    status: NewsletterStatus
    scheduled_for: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    recipient_filters: Optional[Dict[str, Any]] = None
    total_recipients: int
    total_sent: int
    created_by: UUID


class NewsletterPublic(BaseSchema):
    """Public newsletter schema"""

    id: UUID
    subject: str
    status: NewsletterStatus
    scheduled_for: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    total_recipients: int
    total_sent: int
    created_at: datetime


class NewsletterDetail(NewsletterPublic):
    """Detailed newsletter schema"""

    content: str
    template_name: Optional[str] = None
    recipient_filters: Optional[Dict[str, Any]] = None
    created_by_name: str


class NewsletterSend(BaseSchema):
    """Schema for sending a newsletter"""

    send_immediately: bool = False
    test_emails: Optional[List[EmailStr]] = None


class SubscriptionBase(BaseSchema):
    """Base subscription schema"""

    patient_id: UUID
    email: EmailStr


class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription"""

    preferences: Optional[Dict[str, Any]] = None


class SubscriptionUpdate(BaseSchema):
    """Schema for updating a subscription"""

    status: Optional[SubscriptionStatus] = None
    preferences: Optional[Dict[str, Any]] = None


class SubscriptionInDB(IDMixin, TenantMixin, SubscriptionBase, TimestampMixin):
    """Subscription schema for database representation"""

    status: SubscriptionStatus
    preferences: Dict[str, Any]
    unsubscribed_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None


class SubscriptionPublic(BaseSchema):
    """Public subscription schema"""

    id: UUID
    patient_id: UUID
    email: EmailStr
    status: SubscriptionStatus
    patient_name: str
