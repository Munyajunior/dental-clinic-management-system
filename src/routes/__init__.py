# src/routes/__init__.py
from fastapi import APIRouter
from .auth import router as auth_router
from .tenants import router as tenants_router
from .users import router as users_router
from .patients import router as patients_router
from .appointments import router as appointments_router
from .services import router as services_router
from .consultations import router as consultations_router
from .treatments import router as treatments_router
from .invoices import router as invoices_router
from .medical_records import router as medical_records_router
from .prescriptions import router as prescriptions_router
from .newsletters import router as newsletters_router
from .dashboard import router as dashboard_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(tenants_router)
api_router.include_router(users_router)
api_router.include_router(patients_router)
api_router.include_router(appointments_router)
api_router.include_router(services_router)
api_router.include_router(consultations_router)
api_router.include_router(treatments_router)
api_router.include_router(invoices_router)
api_router.include_router(medical_records_router)
api_router.include_router(prescriptions_router)
api_router.include_router(newsletters_router)
api_router.include_router(dashboard_router)
