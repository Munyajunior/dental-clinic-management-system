# src/services/tenant_service.py
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from sqlalchemy import select, func
from fastapi import HTTPException, status
from models.tenant import Tenant, TenantTier, TenantStatus
from schemas.tenant_schemas import TenantCreate, TenantUpdate, TenantStats
from services.auth_service import auth_service
from utils.logger import setup_logger
from .base_service import BaseService

logger = setup_logger("TENANT_SERVICE")


class TenantService(BaseService):
    def __init__(self):
        super().__init__(Tenant)

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[Tenant]:
        """Get tenant by slug"""
        try:
            result = await db.execute(
                select(Tenant).where(Tenant.slug == slug, Tenant.status == "active")
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting tenant by slug {slug}: {e}")
            return None

    async def create_tenant(
        self, db: AsyncSession, tenant_data: TenantCreate
    ) -> Tenant:
        """Create new tenant with validation"""
        # Check if slug already exists
        result = await db.execute(select(Tenant).where(Tenant.slug == tenant_data.slug))
        existing_tenant = result.scalar_one_or_none()
        if existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tenant with this slug already exists",
            )

        # Create tenant
        tenant = Tenant(**tenant_data.dict())
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

        logger.info(f"Created new tenant: {tenant.name} ({tenant.slug})")
        return tenant

    async def create_tenant_with_admin(
        self, db: AsyncSession, tenant_data: TenantCreate
    ) -> Tenant:
        """Create tenant with admin user and send welcome email"""
        try:
            # Check if slug already exists
            existing_tenant = await self.get_by_slug(db, tenant_data.slug)
            if existing_tenant:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tenant with this slug already exists",
                )

            # Create tenant
            tenant = Tenant(**tenant_data.dict())
            db.add(tenant)
            await db.commit()
            await db.refresh(tenant)

            # Create admin user for the tenant
            admin_user = await auth_service.create_tenant_admin_user(
                db, tenant, tenant_data.contact_email
            )

            logger.info(
                f"Created tenant {tenant.name} with admin user {admin_user.email}"
            )
            return tenant

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create tenant with admin: {e}")
            raise

    async def get_tenant_stats(self, db: AsyncSession, tenant_id: UUID) -> TenantStats:
        """Get tenant statistics"""
        from models.user import User
        from models.patient import Patient
        from models.appointment import Appointment
        from models.invoice import Invoice

        try:
            # Get counts
            users_count = await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tenant_id)
            )
            patients_count = await db.execute(
                select(func.count())
                .select_from(Patient)
                .where(Patient.tenant_id == tenant_id)
            )
            appointments_count = await db.execute(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.tenant_id == tenant_id)
            )
            invoices_count = await db.execute(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.tenant_id == tenant_id)
            )

            # Get monthly revenue (simplified)
            monthly_revenue_result = await db.execute(
                select(func.sum(Invoice.total_amount)).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.status == "paid",
                    func.extract("month", Invoice.paid_date)
                    == func.extract("month", func.now()),
                    func.extract("year", Invoice.paid_date)
                    == func.extract("year", func.now()),
                )
            )
            monthly_revenue = monthly_revenue_result.scalar() or 0

            # Get active patients (visited in last 30 days)
            from datetime import datetime, timedelta

            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            active_patients_count = await db.execute(
                select(func.count(func.distinct(Appointment.patient_id))).where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.appointment_date >= thirty_days_ago,
                )
            )

            return TenantStats(
                total_users=users_count.scalar(),
                total_patients=patients_count.scalar(),
                total_appointments=appointments_count.scalar(),
                total_invoices=invoices_count.scalar(),
                monthly_revenue=float(monthly_revenue),
                active_patients=active_patients_count.scalar(),
            )
        except Exception as e:
            logger.error(f"Error getting tenant stats for {tenant_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not retrieve tenant statistics",
            )


tenant_service = TenantService()
