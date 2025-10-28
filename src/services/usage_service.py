from typing import Optional, Dict, Any
from uuid import UUID

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models.tenant import Tenant
from models.user import User
from models.patient import Patient
from models.appointment import Appointment


class UsageService:
    """Service for tracking and managing tenant usage"""

    async def get_tenant_usage(
        self, db: AsyncSession, tenant_id: UUID
    ) -> Dict[str, Any]:
        """Get comprehensive usage statistics for a tenant"""
        # Get user count
        user_count = await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id, User.is_active
            )
        )

        # Get patient count
        patient_count = await db.execute(
            select(func.count(Patient.id)).where(Patient.tenant_id == tenant_id)
        )

        # Get appointment count (this month)
        start_of_month = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        appointment_count = await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.tenant_id == tenant_id,
                Appointment.created_at >= start_of_month,
            )
        )

        # TODO: Implement storage usage calculation
        # TODO: Implement API call tracking

        return {
            "active_users": user_count.scalar() or 0,
            "patient_count": patient_count.scalar() or 0,
            "appointments_this_month": appointment_count.scalar() or 0,
            "storage_used_gb": 0.0,  # Placeholder
            "api_calls_this_month": 0,  # Placeholder
        }
