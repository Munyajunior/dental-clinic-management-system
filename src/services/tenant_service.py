# src/services/tenant_service.py
from typing import Optional
from uuid import UUID, uuid4
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from fastapi import HTTPException, status, BackgroundTasks
from passlib.context import CryptContext
from models.tenant import (
    Tenant,
    TenantTier,
    TenantStatus,
    TenantPaymentStatus,
    BillingCycle,
)
from schemas.tenant_schemas import TenantCreate, TenantUpdate, TenantStats
from models.user import User, GenderEnum, StaffRole
from models.patient import Patient
from models.appointment import Appointment
from models.invoice import Invoice
from services.email_service import email_service
from utils.logger import setup_logger
from .base_service import BaseService
import secrets
import string

logger = setup_logger("TENANT_SERVICE")

# Password context for hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


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

    def _generate_pronounceable_password(self, length: int = 12) -> str:
        """Generate secure, pronounceable passwords"""
        vowels = "aeiou"
        consonants = "bcdfghjklmnpqrstvwxyz"

        # Ensure minimum strength
        while True:
            password = []
            for i in range(length):
                if i % 2 == 0:
                    password.append(secrets.choice(consonants))
                else:
                    password.append(secrets.choice(vowels))

            # Add required character types
            password.append(secrets.choice(string.ascii_uppercase))
            password.append(secrets.choice(string.digits))
            password.append(secrets.choice("!@#$%"))

            secrets.SystemRandom().shuffle(password)
            result = "".join(password)

            # Basic validation
            if (
                len(result) >= 8
                and any(c.isupper() for c in result)
                and any(c.islower() for c in result)
                and any(c.isdigit() for c in result)
            ):
                return result

    def _get_password_hash(self, password: str) -> str:
        """Hash password"""
        return pwd_context.hash(password)

    async def _create_tenant_admin_user(
        self,
        db: AsyncSession,
        tenant: Tenant,
        email: str,
        background_tasks: BackgroundTasks,
    ) -> User:
        """Create default admin user for new tenant (without using auth_service.create_user)"""
        try:
            # Generate temporary password
            temp_password = self._generate_pronounceable_password()

            # Create user directly with all required fields
            user = User(
                id=uuid4(),
                tenant_id=tenant.id,
                email=email,
                first_name="Clinic",
                last_name="Admin",
                contact_number="",
                gender=GenderEnum.OTHER,
                role=StaffRole.ADMIN,
                hashed_password=self._get_password_hash(temp_password),
                specialization=None,
                license_number=None,
                employee_id=None,
                max_patients=50,
                is_accepting_new_patients=True,
                availability_schedule={},
                permissions={
                    "Admin": [
                        "user_manage",
                        "patient_manage",
                        "appointment_manage",
                        "prescription_manage",
                        "medical_records_manage",
                        "services_manage",
                        "invoice_manage",
                        "treatment_manage",
                        "report_view",
                        "settings_manage",
                    ]
                },
                work_schedule={},
                is_available=True,
                is_active=True,
                is_verified=False,
                settings={
                    "login_count": 0,
                    "account_locked_until": None,
                    "temporary_password": True,
                    "force_password_reset": True,
                    "password_changed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            db.add(user)
            await db.flush()  # Get user ID without committing

            logger.info(
                f"Created tenant admin user: {email} for tenant: {tenant.name} with password: {temp_password}"
            )

            # Send welcome email in background
            background_tasks.add_task(
                self._send_tenant_welcome_email_background,
                user_email=email,
                user_name=f"{user.first_name} {user.last_name}",
                temp_password=temp_password,
                tenant_slug=tenant.slug,
            )

            return user

        except Exception as e:
            logger.error(f"Failed to create tenant admin user: {e}")
            raise

    async def _send_tenant_welcome_email_background(
        self, user_email: str, user_name: str, temp_password: str, tenant_slug: str
    ):
        """Send welcome email in background task"""
        try:
            await email_service.send_tenant_welcome_email(
                user_email=user_email,
                user_name=user_name,
                temp_password=temp_password,
                tenant_slug=tenant_slug,
            )
            logger.info(f"Welcome email sent to {user_email}")
        except Exception as e:
            logger.error(f"Failed to send welcome email to {user_email}: {e}")
            # Log credentials for manual recovery if email fails
            logger.warning(
                f"MANUAL RECOVERY - Tenant admin credentials: "
                f"Email: {user_email}, Temp Password: {temp_password}, "
                f"Tenant: {tenant_slug}"
            )

    async def create_tenant_with_admin(
        self,
        db: AsyncSession,
        tenant_data: TenantCreate,
        background_tasks: BackgroundTasks,
    ) -> Tenant:
        """Create tenant with admin user using internal method"""
        try:
            # Check if slug already exists
            existing_tenant = await self.get_by_slug(db, tenant_data.slug)
            if existing_tenant:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A clinic with this URL already exists. Please choose a different clinic name or URL.",
                )

            # Create tenant with proper defaults
            tenant_dict = tenant_data.model_dump()

            # Ensure proper defaults for tenant
            tenant_dict.setdefault("tier", TenantTier.BASIC)
            tenant_dict.setdefault("payment_status", TenantPaymentStatus.PENDING)
            tenant_dict.setdefault("status", TenantStatus.ACTIVE)
            tenant_dict.setdefault("billing_cycle", BillingCycle.MONTHLY)
            tenant_dict.setdefault("max_users", 5)
            tenant_dict.setdefault("max_patients", 1000)
            tenant_dict.setdefault("max_storage_gb", 1)
            tenant_dict.setdefault("max_api_calls_per_month", 10000)
            tenant_dict.setdefault("current_user_count", 0)
            tenant_dict.setdefault("current_patient_count", 0)
            tenant_dict.setdefault("current_storage_gb", 0.0)
            tenant_dict.setdefault("current_api_calls_this_month", 0)
            tenant_dict.setdefault("isolation_level", "shared")
            tenant_dict.setdefault("enabled_features", {})
            tenant_dict.setdefault("settings", {})
            tenant_dict.setdefault("restrictions", {})

            # Create and add tenant
            tenant = Tenant(**tenant_dict)
            db.add(tenant)
            await db.flush()  # Get tenant ID without committing

            logger.info(f"Created tenant: {tenant.name} with ID: {tenant.id}")

            try:
                # Create admin user for the tenant using internal method
                admin_user = await self._create_tenant_admin_user(
                    db, tenant, tenant_data.contact_email, background_tasks
                )

                # Now commit both tenant and user together
                await db.commit()
                await db.refresh(tenant)

                logger.info(
                    f"Successfully created tenant {tenant.name} with admin user {admin_user.email}"
                )
                return tenant

            except Exception as user_error:
                # If user creation fails, rollback the entire transaction
                await db.rollback()
                logger.error(
                    f"Failed to create admin user for tenant {tenant.name}: {user_error}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create clinic administrator account. Please try again.",
                )

        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to create tenant with admin: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create clinic account. Please try again or contact support.",
            )

    async def create_tenant(
        self, db: AsyncSession, tenant_data: TenantCreate
    ) -> Tenant:
        """Create new tenant with validation (without admin user)"""
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

    async def get_tenant_stats(self, db: AsyncSession, tenant_id: UUID) -> TenantStats:
        """Get tenant statistics"""
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

            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
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
