# src/schemas/email_schemas.py
from pydantic import BaseModel, EmailStr, validator
from typing import Dict, Any, List, Optional
from enum import Enum


class EmailPriority(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class EmailType(str, Enum):
    WELCOME_TENANT = "welcome_tenant"
    EMAIL_VERIFICATION = "email_verification"
    APPOINTMENT_CONFIRMATION = "appointment_confirmation"
    APPOINTMENT_REMINDER = "appointment_reminder"
    APPOINTMENT_CANCELLATION = "appointment_cancellation"
    WELCOME_PATIENT = "welcome_patient"
    WELCOME_STAFF = "welcome_staff"
    PASSWORD_RESET = "password_reset"
    INVOICE_SENT = "invoice_sent"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    PRESCRIPTION_READY = "prescription_ready"
    NEWSLETTER = "newsletter"
    SECURITY_ALERT = "security_alert"


class EmailAttachment(BaseModel):
    """Email attachment schema"""

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class EmailRequest(BaseModel):
    """Base email request schema"""

    to: List[EmailStr]
    subject: str
    template_name: str
    template_data: Dict[str, Any]
    cc: Optional[List[EmailStr]] = None
    bcc: Optional[List[EmailStr]] = None
    reply_to: Optional[EmailStr] = None
    attachments: Optional[List[EmailAttachment]] = None
    priority: EmailPriority = EmailPriority.NORMAL

    @validator("to")
    def validate_recipients(cls, v):
        if not v:
            raise ValueError("At least one recipient is required")
        return v


class EmailResponse(BaseModel):
    """Email response schema"""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    recipients: List[EmailStr]


class BulkEmailRequest(BaseModel):
    """Bulk email request schema"""

    emails: List[EmailRequest]
    batch_size: int = 50


class EmailTemplate(BaseModel):
    """Email template schema"""

    name: str
    subject: str
    html_template: str
    text_template: Optional[str] = None
    description: Optional[str] = None
    variables: List[str] = []
