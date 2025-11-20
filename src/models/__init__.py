# src/models/__init__.py
"""
Models initialization file to handle circular dependencies
"""

# Import all models first
from .tenant import Tenant
from .user import User
from .patient import Patient
from .service import Service
from .appointment import Appointment
from .consultation import Consultation
from .treatment import Treatment
from .treatment_item import TreatmentItem
from .medical_record import MedicalRecord
from .prescription import Prescription
from .invoice import Invoice, InvoiceItem, Payment
from .newsletter import Newsletter, NewsletterSubscription
from .settings import TenantSettings, SettingsAudit
from .auth import (
    RefreshToken,
    PasswordResetToken,
    LoginAttempt,
    SecurityEvent,
    UserSession,
)
from .treatment_template import TreatmentTemplate, TreatmentTemplateItem
from .patient_sharing import PatientSharing

# Now configure relationships that require cross-references
from sqlalchemy.orm import configure_mappers, relationship

# Configure Tenant settings relationship
Tenant.settings_entries = relationship(
    "TenantSettings", back_populates="tenant", cascade="all, delete-orphan"
)

# Configure all mappers
configure_mappers()

__all__ = [
    "Tenant",
    "User",
    "Patient",
    "Service",
    "Appointment",
    "Consultation",
    "Treatment",
    "TreatmentItem",
    "MedicalRecord",
    "Prescription",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "Newsletter",
    "NewsletterSubscription",
    "TenantSettings",
    "SettingsAudit",
    "RefreshToken",
    "PasswordResetToken",
    "LoginAttempt",
    "SecurityEvent",
    "UserSession",
    "TreatmentTemplate",
    "TreatmentTemplateItem",
    "PatientSharing",
]
