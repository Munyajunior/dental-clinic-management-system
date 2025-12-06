# src/services/appointment_service.py (Updated)
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status
from models.appointment import Appointment, AppointmentStatus, AppointmentType
from models.user import User
from models.patient import Patient, PatientStatus
from schemas.appointment_schemas import (
    AppointmentCreate,
    AppointmentUpdate,
    AppointmentSearch,
    AppointmentSlot,
)
from utils.logger import setup_logger
from .base_service import BaseService
from .email_integration_service import email_integration_service

logger = setup_logger("APPOINTMENT_SERVICE")


class AppointmentService(BaseService):
    def __init__(self):
        super().__init__(Appointment)

    async def create_appointment(
        self, db: AsyncSession, appointment_data: AppointmentCreate
    ) -> Appointment:
        """Create new appointment with validation and email notification"""
        # Verify dentist exists and is available
        dentist_result = await db.execute(
            select(User).where(
                User.id == appointment_data.dentist_id,
                User.is_active,
                User.is_available,
            )
        )
        dentist = dentist_result.scalar_one_or_none()
        if not dentist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dentist not found or not available",
            )

        # Verify patient exists
        patient_result = await db.execute(
            select(Patient).where(
                Patient.id == appointment_data.patient_id,
                Patient.status == PatientStatus.ACTIVE,
            )
        )
        patient = patient_result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Patient not found"
            )

        # Check for scheduling conflicts
        conflict_result = await db.execute(
            select(Appointment).where(
                Appointment.dentist_id == appointment_data.dentist_id,
                Appointment.appointment_date
                >= appointment_data.appointment_date - timedelta(minutes=30),
                Appointment.appointment_date
                <= appointment_data.appointment_date
                + timedelta(minutes=appointment_data.duration_minutes),
                Appointment.status.in_(
                    [
                        AppointmentStatus.SCHEDULED,
                        AppointmentStatus.CONFIRMED,
                        AppointmentStatus.IN_PROGRESS,
                    ]
                ),
            )
        )
        conflicting_appointment = conflict_result.scalar_one_or_none()
        if conflicting_appointment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Appointment time conflicts with existing appointment",
            )

        appointment = Appointment(**appointment_data.dict())
        db.add(appointment)
        await db.commit()
        await db.refresh(appointment)

        # Send confirmation email
        try:
            await email_integration_service.send_appointment_confirmation_email(
                db, appointment.id
            )
            logger.info(
                f"Appointment confirmation email sent for appointment {appointment.id}"
            )
        except Exception as e:
            logger.error(f"Failed to send appointment confirmation email: {e}")
            # Don't fail the appointment creation if email fails

        logger.info(f"Created new appointment: {appointment.id}")
        return appointment

    async def search_appointments(
        self,
        db: AsyncSession,
        search_params: AppointmentSearch,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Appointment]:
        """Search appointments with various filters"""
        try:
            query = select(Appointment)

            # Dentist filter
            if search_params.dentist_id:
                query = query.where(Appointment.dentist_id == search_params.dentist_id)

            # Patient filter
            if search_params.patient_id:
                query = query.where(Appointment.patient_id == search_params.patient_id)

            # Status filter
            if search_params.status:
                query = query.where(Appointment.status == search_params.status)

            # Type filter
            if search_params.appointment_type:
                query = query.where(
                    Appointment.appointment_type == search_params.appointment_type
                )

            # Date range filter
            if search_params.date_from:
                query = query.where(
                    Appointment.appointment_date >= search_params.date_from
                )
            if search_params.date_to:
                query = query.where(
                    Appointment.appointment_date <= search_params.date_to
                )

            # Urgent filter
            if search_params.is_urgent is not None:
                query = query.where(Appointment.is_urgent == search_params.is_urgent)

            query = (
                query.offset(skip).limit(limit).order_by(Appointment.appointment_date)
            )
            result = await db.execute(query)
            appointments = result.scalars().all()

            # Eager load related data
            for appointment in appointments:
                await db.refresh(appointment, ["patient", "dentist"])

            return appointments

        except Exception as e:
            logger.error(f"Error searching appointments: {e}")
            return []

    async def get_available_slots(
        self, db: AsyncSession, dentist_id: UUID, date: date, duration_minutes: int = 30
    ) -> List[AppointmentSlot]:
        """Get available appointment slots for a dentist on a specific date"""
        try:
            # Get dentist work schedule
            dentist_result = await db.execute(select(User).where(User.id == dentist_id))
            dentist = dentist_result.scalar_one_or_none()
            if not dentist:
                return []

            # Default working hours (9 AM to 5 PM)
            work_start = datetime.combine(date, datetime.min.time().replace(hour=9))
            work_end = datetime.combine(date, datetime.min.time().replace(hour=17))

            # Get dentist's custom schedule if available
            if dentist.work_schedule:
                # Parse work schedule from JSON
                schedule = dentist.work_schedule
                day_name = date.strftime("%A").lower()
                if day_name in schedule and schedule[day_name]:
                    # Use custom schedule for this day
                    time_slots = schedule[day_name]
                    if time_slots:
                        start_time_str = time_slots[0].split("-")[0]
                        end_time_str = time_slots[0].split("-")[1]

                        start_hour, start_minute = map(int, start_time_str.split(":"))
                        end_hour, end_minute = map(int, end_time_str.split(":"))

                        work_start = datetime.combine(
                            date,
                            datetime.min.time().replace(
                                hour=start_hour, minute=start_minute
                            ),
                        )
                        work_end = datetime.combine(
                            date,
                            datetime.min.time().replace(
                                hour=end_hour, minute=end_minute
                            ),
                        )

            # Get existing appointments for the day
            day_start = datetime.combine(date, datetime.min.time())
            day_end = datetime.combine(date, datetime.max.time())

            appointments_result = await db.execute(
                select(Appointment)
                .where(
                    Appointment.dentist_id == dentist_id,
                    Appointment.appointment_date >= day_start,
                    Appointment.appointment_date <= day_end,
                    Appointment.status.in_(
                        [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED]
                    ),
                )
                .order_by(Appointment.appointment_date)
            )
            appointments = appointments_result.scalars().all()

            # Generate available slots
            slots = []
            current_time = work_start
            slot_duration = timedelta(minutes=duration_minutes)

            while current_time + slot_duration <= work_end:
                slot_end = current_time + slot_duration

                # Check if slot is available (no overlapping appointments)
                is_available = True
                for appointment in appointments:
                    appointment_end = appointment.appointment_date + timedelta(
                        minutes=appointment.duration_minutes
                    )
                    if (
                        current_time < appointment_end
                        and slot_end > appointment.appointment_date
                    ):
                        is_available = False
                        break

                slots.append(
                    AppointmentSlot(
                        start_time=current_time,
                        end_time=slot_end,
                        is_available=is_available,
                        dentist_id=dentist_id,
                        dentist_name=f"{dentist.first_name} {dentist.last_name}",
                    )
                )

                current_time += slot_duration

            return slots

        except Exception as e:
            logger.error(f"Error getting available slots: {e}")
            return []

    async def update_status(
        self,
        db: AsyncSession,
        appointment_id: UUID,
        apt_status: AppointmentStatus,
        cancellation_reason: Optional[str] = None,
    ) -> Optional[Appointment]:
        """Update appointment status with email notifications"""
        appointment = await self.get(db, appointment_id)
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found"
            )

        old_status = appointment.status
        appointment.status = apt_status

        # Set timestamps based on status
        now = datetime.now(timezone.utc)
        if apt_status == AppointmentStatus.CONFIRMED:
            appointment.confirmed_at = now
        elif apt_status == AppointmentStatus.COMPLETED:
            appointment.completed_at = now
        elif apt_status == AppointmentStatus.CANCELLED:
            appointment.cancelled_at = now
            appointment.cancellation_reason = cancellation_reason

        await db.commit()
        await db.refresh(appointment)

        # Send email notifications for status changes
        try:
            if old_status != apt_status:
                if apt_status == AppointmentStatus.CONFIRMED:
                    await email_integration_service.send_appointment_confirmation_email(
                        db, appointment_id
                    )
                elif apt_status == AppointmentStatus.CANCELLED:
                    # Send cancellation email
                    await self._send_cancellation_email(db, appointment)
        except Exception as e:
            logger.error(f"Failed to send status change email: {e}")

        logger.info(f"Updated appointment {appointment_id} status to {status}")
        return appointment

    async def _send_cancellation_email(
        self, db: AsyncSession, appointment: Appointment
    ):
        """Send appointment cancellation email"""
        try:
            # Get patient and dentist details
            await db.refresh(appointment, ["patient", "dentist"])

            template_data = {
                "patient_name": f"{appointment.patient.first_name} {appointment.patient.last_name}",
                "appointment_date": appointment.appointment_date.strftime(
                    "%B %d, %Y at %I:%M %p"
                ),
                "dentist_name": f"Dr. {appointment.dentist.first_name} {appointment.dentist.last_name}",
                "cancellation_reason": appointment.cancellation_reason
                or "No reason provided",
                "clinic_name": "Dental Clinic",
                "contact_email": "contact@dentalclinic.com",
            }

            from services.email_service import email_service, EmailType

            await email_service.send_templated_email(
                EmailType.APPOINTMENT_CANCELLATION,
                to=[appointment.patient.email],
                template_data=template_data,
            )

        except Exception as e:
            logger.error(f"Error sending cancellation email: {e}")

    async def get_upcoming_appointments(
        self, db: AsyncSession, days: int = 7
    ) -> List[Appointment]:
        """Get upcoming appointments within the next N days"""
        try:
            start_date = datetime.now(timezone.utc)
            end_date = start_date + timedelta(days=days)

            result = await db.execute(
                select(Appointment)
                .where(
                    Appointment.appointment_date >= start_date,
                    Appointment.appointment_date <= end_date,
                    Appointment.status.in_(
                        [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED]
                    ),
                )
                .order_by(Appointment.appointment_date)
            )
            appointments = result.scalars().all()

            # Eager load related data
            for appointment in appointments:
                await db.refresh(appointment, ["patient", "dentist"])

            return appointments
        except Exception as e:
            logger.error(f"Error getting upcoming appointments: {e}")
            return []

    async def send_reminders_for_tomorrow(self, db: AsyncSession) -> Dict[str, Any]:
        """Send reminders for tomorrow's appointments"""
        try:
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            result = await db.execute(
                select(Appointment).where(
                    Appointment.appointment_date.between(tomorrow_start, tomorrow_end),
                    Appointment.status.in_(
                        [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED]
                    ),
                    Appointment.reminder_sent == False,  # Only send once
                )
            )
            appointments = result.scalars().all()

            success_count = 0
            failure_count = 0

            for appointment in appointments:
                try:
                    await db.refresh(appointment, ["patient", "dentist"])

                    # Send reminder email
                    from services.email_service import email_service, EmailType

                    template_data = {
                        "patient_name": f"{appointment.patient.first_name} {appointment.patient.last_name}",
                        "appointment_date": appointment.appointment_date.strftime(
                            "%B %d, %Y at %I:%M %p"
                        ),
                        "dentist_name": f"Dr. {appointment.dentist.first_name} {appointment.dentist.last_name}",
                        "days_until": 1,
                        "clinic_name": "Dental Clinic",
                        "contact_email": "contact@dentalclinic.com",
                    }

                    await email_service.send_templated_email(
                        EmailType.APPOINTMENT_REMINDER,
                        to=[appointment.patient.email],
                        template_data=template_data,
                    )

                    # Mark as reminder sent
                    appointment.reminder_sent = True
                    success_count += 1

                except Exception as e:
                    logger.error(
                        f"Failed to send reminder for appointment {appointment.id}: {e}"
                    )
                    failure_count += 1

            await db.commit()

            return {
                "total_appointments": len(appointments),
                "success_count": success_count,
                "failure_count": failure_count,
            }

        except Exception as e:
            logger.error(f"Error sending reminders: {e}")
            return {"error": str(e)}


appointment_service = AppointmentService()
