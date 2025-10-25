# src/routes/__init__.py
from .auth import router as auth_router
from .tenants import router as tenants_router
from .users import router as users_router
from .patients import router as patients_router
from .appointments import router as appointments_router
from .services import router as services_router
from .consultations import router as consultations_router
from .treatments import router as treatments_router
from .email import router as email_router
from .invoices import router as invoices_router
from .medical_records import router as medical_records_router
from .prescriptions import router as prescriptions_router
from .newsletters import router as newsletters_router
from .dashboard import router as dashboard_router
from .settings import router as settings_router
from .public import router as public_router

__all__ = [
    "auth_router",
    "tenants_router",
    "users_router",
    "patients_router",
    "appointments_router",
    "services_router",
    "email_router",
    "consultations_router",
    "treatments_router",
    "invoices_router",
    "medical_records_router",
    "prescriptions_router",
    "newsletters_router",
    "dashboard_router",
    "settings_router",
    "public_router",
]
