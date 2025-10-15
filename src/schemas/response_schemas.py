# src/schemas/response_schemas.py
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from decimal import Decimal


class DashboardStats(BaseModel):
    """Dashboard statistics schema"""

    total_patients: int
    total_appointments: int
    total_invoices: int
    monthly_revenue: float
    pending_appointments: int
    overdue_invoices: int


class RevenueOverview(BaseModel):
    """Revenue overview schema"""

    monthly_revenue: Dict[str, float]
    revenue_by_method: Dict[str, float]
    top_services: List[Dict[str, Any]]
    period_months: int


class AppointmentsOverview(BaseModel):
    """Appointments overview schema"""

    appointments_by_status: Dict[str, int]
    appointments_by_day: Dict[str, int]
    top_dentists: List[Dict[str, Any]]
    period_days: int


class TreatmentStats(BaseModel):
    """Treatment statistics schema"""

    treatments_by_status: Dict[str, int]
    active_treatments: int
    completed_treatments_recent: int
