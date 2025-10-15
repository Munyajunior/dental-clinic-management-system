# src/services/dashboard_service.py
from typing import Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, extract
from fastapi import HTTPException, status
from models.user import User
from models.patient import Patient
from models.appointment import Appointment, AppointmentStatus
from models.consultation import Consultation
from models.treatment import Treatment, TreatmentStatus
from models.invoice import Invoice, InvoiceStatus, InvoiceItem, Payment
from schemas.response_schemas import DashboardStats
from utils.logger import setup_logger

logger = setup_logger("DASHBOARD_SERVICE")


class DashboardService:
    def __init__(self):
        pass

    async def get_dashboard_stats(self, db: AsyncSession) -> DashboardStats:
        """Get comprehensive dashboard statistics"""
        try:
            # Total patients
            patients_result = await db.execute(select(func.count(Patient.id)))
            total_patients = patients_result.scalar()

            # Total appointments (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            appointments_result = await db.execute(
                select(func.count(Appointment.id)).where(
                    Appointment.appointment_date >= thirty_days_ago
                )
            )
            total_appointments = appointments_result.scalar()

            # Total invoices (last 30 days)
            invoices_result = await db.execute(
                select(func.count(Invoice.id)).where(
                    Invoice.created_at >= thirty_days_ago
                )
            )
            total_invoices = invoices_result.scalar()

            # Monthly revenue (current month)
            today = date.today()
            first_day = today.replace(day=1)
            next_month = today.replace(day=28) + timedelta(
                days=4
            )  # Safe way to get next month
            last_day = next_month - timedelta(days=next_month.day)

            revenue_result = await db.execute(
                select(func.sum(Invoice.total_amount)).where(
                    and_(
                        Invoice.status == InvoiceStatus.PAID,
                        Invoice.paid_date >= first_day,
                        Invoice.paid_date <= last_day,
                    )
                )
            )
            monthly_revenue = revenue_result.scalar() or Decimal("0.00")

            # Pending appointments (today and future)
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            pending_appointments_result = await db.execute(
                select(func.count(Appointment.id)).where(
                    and_(
                        Appointment.status.in_(
                            [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED]
                        ),
                        Appointment.appointment_date >= today_start,
                    )
                )
            )
            pending_appointments = pending_appointments_result.scalar()

            # Overdue invoices
            overdue_invoices_result = await db.execute(
                select(func.count(Invoice.id)).where(
                    and_(
                        Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.PARTIAL]),
                        Invoice.due_date < datetime.utcnow(),
                    )
                )
            )
            overdue_invoices = overdue_invoices_result.scalar()

            return DashboardStats(
                total_patients=total_patients,
                total_appointments=total_appointments,
                total_invoices=total_invoices,
                monthly_revenue=float(monthly_revenue),
                pending_appointments=pending_appointments,
                overdue_invoices=overdue_invoices,
            )

        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            return DashboardStats(
                total_patients=0,
                total_appointments=0,
                total_invoices=0,
                monthly_revenue=0.0,
                pending_appointments=0,
                overdue_invoices=0,
            )

    async def get_appointments_overview(
        self, db: AsyncSession, days: int = 30
    ) -> Dict[str, Any]:
        """Get appointments overview for dashboard"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            # Appointments by status
            status_result = await db.execute(
                select(Appointment.status, func.count(Appointment.id))
                .where(Appointment.appointment_date >= start_date)
                .group_by(Appointment.status)
            )
            appointments_by_status = {row[0]: row[1] for row in status_result}

            # Appointments by day (last 7 days)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            daily_result = await db.execute(
                select(
                    func.date(Appointment.appointment_date).label("date"),
                    func.count(Appointment.id),
                )
                .where(Appointment.appointment_date >= seven_days_ago)
                .group_by("date")
                .order_by("date")
            )
            appointments_by_day = {row[0].isoformat(): row[1] for row in daily_result}

            # Top dentists by appointments
            dentists_result = await db.execute(
                select(
                    User.first_name,
                    User.last_name,
                    func.count(Appointment.id).label("appointment_count"),
                )
                .join(Appointment, Appointment.dentist_id == User.id)
                .where(Appointment.appointment_date >= start_date)
                .group_by(User.id, User.first_name, User.last_name)
                .order_by(func.count(Appointment.id).desc())
                .limit(5)
            )
            top_dentists = [
                {"name": f"{row[0]} {row[1]}", "count": row[2]}
                for row in dentists_result
            ]

            return {
                "appointments_by_status": appointments_by_status,
                "appointments_by_day": appointments_by_day,
                "top_dentists": top_dentists,
                "period_days": days,
            }

        except Exception as e:
            logger.error(f"Error getting appointments overview: {e}")
            return {}

    async def get_revenue_overview(
        self, db: AsyncSession, months: int = 12
    ) -> Dict[str, Any]:
        """Get revenue overview for dashboard"""
        try:
            start_date = datetime.utcnow() - timedelta(days=months * 30)

            # Revenue by month
            monthly_revenue_result = await db.execute(
                select(
                    extract("year", Invoice.paid_date).label("year"),
                    extract("month", Invoice.paid_date).label("month"),
                    func.sum(Invoice.total_amount).label("revenue"),
                )
                .where(
                    and_(
                        Invoice.status == InvoiceStatus.PAID,
                        Invoice.paid_date >= start_date,
                    )
                )
                .group_by("year", "month")
                .order_by("year", "month")
            )

            monthly_revenue = {}
            for row in monthly_revenue_result:
                month_key = f"{int(row[0])}-{int(row[1]):02d}"
                monthly_revenue[month_key] = float(row[2])

            # Revenue by payment method
            payment_method_result = await db.execute(
                select(Payment.payment_method, func.sum(Payment.amount).label("amount"))
                .from_(Payment)
                .join(Invoice)
                .where(
                    Invoice.status == InvoiceStatus.PAID,
                    Invoice.paid_date >= start_date,
                )
                .group_by(Payment.payment_method)
            )
            revenue_by_method = {row[0]: float(row[1]) for row in payment_method_result}

            # Top services by revenue
            from models.treatment_item import TreatmentItem
            from models.service import Service

            services_revenue_result = await db.execute(
                select(
                    Service.name,
                    func.sum(TreatmentItem.quantity * TreatmentItem.unit_price).label(
                        "revenue"
                    ),
                )
                .select_from(TreatmentItem)
                .join(Service, TreatmentItem.service_id == Service.id)
                .join(InvoiceItem, InvoiceItem.treatment_item_id == TreatmentItem.id)
                .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
                .where(
                    Invoice.status == InvoiceStatus.PAID,
                    Invoice.paid_date >= start_date,
                )
                .group_by(Service.name)
                .order_by(
                    func.sum(TreatmentItem.quantity * TreatmentItem.unit_price).desc()
                )
                .limit(10)
            )
            top_services = [
                {"service": row[0], "revenue": float(row[1])}
                for row in services_revenue_result
            ]

            return {
                "monthly_revenue": monthly_revenue,
                "revenue_by_method": revenue_by_method,
                "top_services": top_services,
                "period_months": months,
            }

        except Exception as e:
            logger.error(f"Error getting revenue overview: {e}")
            return {}

    async def get_treatment_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """Get treatment statistics for dashboard"""
        try:
            # Treatments by status
            status_result = await db.execute(
                select(Treatment.status, func.count(Treatment.id)).group_by(
                    Treatment.status
                )
            )
            treatments_by_status = {row[0]: row[1] for row in status_result}

            # Active treatments (in progress)
            active_treatments_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    Treatment.status == TreatmentStatus.IN_PROGRESS
                )
            )
            active_treatments = active_treatments_result.scalar()

            # Completed treatments (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            completed_treatments_result = await db.execute(
                select(func.count(Treatment.id)).where(
                    and_(
                        Treatment.status == TreatmentStatus.COMPLETED,
                        Treatment.completed_at >= thirty_days_ago,
                    )
                )
            )
            completed_treatments = completed_treatments_result.scalar()

            return {
                "treatments_by_status": treatments_by_status,
                "active_treatments": active_treatments,
                "completed_treatments_recent": completed_treatments,
            }

        except Exception as e:
            logger.error(f"Error getting treatment stats: {e}")
            return {}


dashboard_service = DashboardService()
