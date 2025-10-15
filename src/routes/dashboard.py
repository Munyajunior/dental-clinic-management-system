# src/routes/dashboard.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
from db.database import get_db
from schemas.response_schemas import DashboardStats
from services.dashboard_service import dashboard_service
from services.auth_service import auth_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/stats",
    response_model=DashboardStats,
    summary="Get dashboard statistics",
    description="Get comprehensive statistics for dashboard",
)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get dashboard statistics endpoint"""
    stats = await dashboard_service.get_dashboard_stats(db)
    return stats


@router.get(
    "/appointments/overview",
    summary="Get appointments overview",
    description="Get appointments overview for dashboard",
)
async def get_appointments_overview(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get appointments overview endpoint"""
    overview = await dashboard_service.get_appointments_overview(db, days)
    return overview


@router.get(
    "/revenue/overview",
    summary="Get revenue overview",
    description="Get revenue overview for dashboard",
)
async def get_revenue_overview(
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(auth_service.get_current_user),
) -> Any:
    """Get revenue overview endpoint"""
    overview = await dashboard_service.get_revenue_overview(db, months)
    return overview
