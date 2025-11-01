# src/services/email_integration_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from services.email_service import email_service, EmailType
from schemas.email_schemas import EmailRequest, BulkEmailRequest, EmailAttachment
from models.appointment import Appointment
from models.patient import Patient
from models.user import User
from models.invoice import Invoice
from models.prescription import Prescription
from utils.logger import setup_logger

logger = setup_logger("EMAIL_INTEGRATION_SERVICE")


class EmailIntegrationService:
    """Service to integrate email functionality with business logic"""

    def __init__(self):
        self.email_service = email_service

    async def send_appointment_confirmation_email(
        self, db: AsyncSession, appointment_id: UUID
    ) -> bool:
        """Send appointment confirmation email"""
        try:
            # Get appointment details
            result = await db.execute(
                select(
                    Appointment,
                    Patient.email,
                    Patient.first_name,
                    Patient.last_name,
                    User.first_name,
                    User.last_name,
                )
                .join(Patient, Appointment.patient_id == Patient.id)
                .join(User, Appointment.dentist_id == User.id)
                .where(Appointment.id == appointment_id)
            )

            appointment_data = result.scalar_one_or_none()
            if not appointment_data:
                logger.error(f"Appointment {appointment_id} not found")
                return False

            (
                appointment,
                patient_email,
                patient_first,
                patient_last,
                dentist_first,
                dentist_last,
            ) = appointment_data

            patient_name = f"{patient_first} {patient_last}"
            dentist_name = f"{dentist_first} {dentist_last}"
            appointment_date = appointment.appointment_date.strftime(
                "%B %d, %Y at %I:%M %p"
            )

            # Send email
            response = await self.email_service.send_appointment_confirmation(
                patient_email=patient_email,
                patient_name=patient_name,
                appointment_date=appointment_date,
                dentist_name=dentist_name,
                appointment_type=appointment.appointment_type.value,
            )

            if response.success:
                logger.info(f"Appointment confirmation sent to {patient_email}")
                return True
            else:
                logger.error(
                    f"Failed to send appointment confirmation: {response.error}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending appointment confirmation: {e}")
            return False

    async def send_appointment_reminder_emails(
        self, db: AsyncSession, days_ahead: int = 1
    ) -> Dict[str, Any]:
        """Send appointment reminder emails for appointments in the next N days"""
        try:
            reminder_date = datetime.utcnow() + timedelta(days=days_ahead)
            reminder_date_start = reminder_date.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            reminder_date_end = reminder_date.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            # Get appointments for the reminder date
            result = await db.execute(
                select(
                    Appointment,
                    Patient.email,
                    Patient.first_name,
                    Patient.last_name,
                    User.first_name,
                    User.last_name,
                )
                .join(Patient, Appointment.patient_id == Patient.id)
                .join(User, Appointment.dentist_id == User.id)
                .where(
                    Appointment.appointment_date.between(
                        reminder_date_start, reminder_date_end
                    ),
                    Appointment.status.in_(["scheduled", "confirmed"]),
                )
            )

            appointments = result.all()
            success_count = 0
            failure_count = 0

            for appointment_data in appointments:
                (
                    appointment,
                    patient_email,
                    patient_first,
                    patient_last,
                    dentist_first,
                    dentist_last,
                ) = appointment_data

                patient_name = f"{patient_first} {patient_last}"
                dentist_name = f"{dentist_first} {dentist_last}"
                appointment_date = appointment.appointment_date.strftime(
                    "%B %d, %Y at %I:%M %p"
                )

                response = await self.email_service.send_appointment_reminder(
                    patient_email=patient_email,
                    patient_name=patient_name,
                    appointment_date=appointment_date,
                    dentist_name=dentist_name,
                    days_until=days_ahead,
                )

                if response.success:
                    success_count += 1
                    logger.info(f"Appointment reminder sent to {patient_email}")
                else:
                    failure_count += 1
                    logger.error(
                        f"Failed to send appointment reminder to {patient_email}: {response.error}"
                    )

            return {
                "total_appointments": len(appointments),
                "success_count": success_count,
                "failure_count": failure_count,
                "reminder_date": reminder_date.date().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error sending appointment reminders: {e}")
            return {"error": str(e)}

    async def send_welcome_email_to_patient(
        self,
        db: AsyncSession,
        patient_id: UUID,
        temporary_password: Optional[str] = None,
    ) -> bool:
        """Send welcome email to new patient"""
        try:
            result = await db.execute(select(Patient).where(Patient.id == patient_id))
            patient = result.scalar_one_or_none()

            if not patient:
                logger.error(f"Patient {patient_id} not found")
                return False

            patient_name = f"{patient.first_name} {patient.last_name}"

            response = await self.email_service.send_welcome_patient(
                patient_email=patient.email,
                patient_name=patient_name,
                temporary_password=temporary_password,
            )

            if response.success:
                logger.info(f"Welcome email sent to {patient.email}")
                return True
            else:
                logger.error(f"Failed to send welcome email: {response.error}")
                return False

        except Exception as e:
            logger.error(f"Error sending welcome email: {e}")
            return False

    async def send_invoice_email(
        self, db: AsyncSession, invoice_id: UUID, invoice_url: Optional[str] = None
    ) -> bool:
        """Send invoice email to patient"""
        try:
            result = await db.execute(
                select(Invoice, Patient.email, Patient.first_name, Patient.last_name)
                .join(Patient, Invoice.patient_id == Patient.id)
                .where(Invoice.id == invoice_id)
            )

            invoice_data = result.scalar_one_or_none()
            if not invoice_data:
                logger.error(f"Invoice {invoice_id} not found")
                return False

            invoice, patient_email, patient_first, patient_last = invoice_data
            patient_name = f"{patient_first} {patient_last}"

            due_date = (
                invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "ASAP"
            )

            response = await self.email_service.send_invoice(
                patient_email=patient_email,
                patient_name=patient_name,
                invoice_number=invoice.invoice_number,
                amount=float(invoice.total_amount),
                due_date=due_date,
                invoice_url=invoice_url,
            )

            if response.success:
                logger.info(f"Invoice email sent to {patient_email}")
                return True
            else:
                logger.error(f"Failed to send invoice email: {response.error}")
                return False

        except Exception as e:
            logger.error(f"Error sending invoice email: {e}")
            return False

    async def send_payment_confirmation_email(
        self,
        db: AsyncSession,
        invoice_id: UUID,
        payment_amount: float,
        payment_method: str,
    ) -> bool:
        """Send payment confirmation email"""
        try:
            result = await db.execute(
                select(Invoice, Patient.email, Patient.first_name, Patient.last_name)
                .join(Patient, Invoice.patient_id == Patient.id)
                .where(Invoice.id == invoice_id)
            )

            invoice_data = result.scalar_one_or_none()
            if not invoice_data:
                logger.error(f"Invoice {invoice_id} not found")
                return False

            invoice, patient_email, patient_first, patient_last = invoice_data
            patient_name = f"{patient_first} {patient_last}"

            response = await self.email_service.send_payment_confirmation(
                patient_email=patient_email,
                patient_name=patient_name,
                invoice_number=invoice.invoice_number,
                amount_paid=payment_amount,
                payment_method=payment_method,
            )

            if response.success:
                logger.info(f"Payment confirmation sent to {patient_email}")
                return True
            else:
                logger.error(f"Failed to send payment confirmation: {response.error}")
                return False

        except Exception as e:
            logger.error(f"Error sending payment confirmation: {e}")
            return False

    async def send_prescription_ready_email(
        self, db: AsyncSession, prescription_id: UUID
    ) -> bool:
        """Send prescription ready notification"""
        try:
            result = await db.execute(
                select(
                    Prescription, Patient.email, Patient.first_name, Patient.last_name
                )
                .join(Patient, Prescription.patient_id == Patient.id)
                .where(Prescription.id == prescription_id)
            )

            prescription_data = result.scalar_one_or_none()
            if not prescription_data:
                logger.error(f"Prescription {prescription_id} not found")
                return False

            prescription, patient_email, patient_first, patient_last = prescription_data
            patient_name = f"{patient_first} {patient_last}"

            template_data = {
                "patient_name": patient_name,
                "medication_name": prescription.medication_name,
                "dentist_name": "Your Dentist",  # Would need to join with User table
                "clinic_name": "Dental Clinic",
                "contact_email": "contact@dentalclinic.com",
            }

            response = await self.email_service.send_templated_email(
                EmailType.PRESCRIPTION_READY,
                to=[patient_email],
                template_data=template_data,
            )

            if response.success:
                logger.info(f"Prescription ready email sent to {patient_email}")
                return True
            else:
                logger.error(
                    f"Failed to send prescription ready email: {response.error}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending prescription ready email: {e}")
            return False

    async def send_bulk_newsletter(
        self,
        db: AsyncSession,
        newsletter_id: UUID,
        test_emails: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send bulk newsletter to subscribers"""
        try:
            from models.newsletter import Newsletter, NewsletterSubscription

            # Get newsletter content
            result = await db.execute(
                select(Newsletter).where(Newsletter.id == newsletter_id)
            )
            newsletter = result.scalar_one_or_none()

            if not newsletter:
                return {"error": "Newsletter not found"}

            # Get subscribers
            if test_emails:
                subscribers = test_emails
            else:
                subscription_result = await db.execute(
                    select(NewsletterSubscription.email).where(
                        NewsletterSubscription.status == "subscribed"
                    )
                )
                subscribers = [row[0] for row in subscription_result]

            # Prepare bulk email request
            email_requests = []
            for email in subscribers:
                email_request = EmailRequest(
                    to=[email],
                    subject=newsletter.subject,
                    template_name="newsletter",
                    template_data={
                        "content": newsletter.content,
                        "clinic_name": "Dental Clinic",
                        "unsubscribe_url": f"https://clinic.com/unsubscribe?email={email}",
                    },
                )
                email_requests.append(email_request)

            bulk_request = BulkEmailRequest(emails=email_requests)
            results = await self.email_service.send_bulk_emails(bulk_request)

            success_count = sum(1 for r in results if r.success)
            failure_count = len(results) - success_count

            return {
                "total_recipients": len(subscribers),
                "success_count": success_count,
                "failure_count": failure_count,
                "test_mode": test_emails is not None,
            }

        except Exception as e:
            logger.error(f"Error sending bulk newsletter: {e}")
            return {"error": str(e)}


# Global email integration service instance
email_integration_service = EmailIntegrationService()
