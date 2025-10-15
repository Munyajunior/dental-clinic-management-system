# src/services/email_service.py
import asyncio
import json
import os
from typing import Dict, Any, List, Optional, Tuple
from uuid import UUID
import aiofiles
import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.email_config import email_settings
from schemas.email_schemas import (
    EmailRequest,
    EmailResponse,
    EmailAttachment,
    BulkEmailRequest,
    EmailType,
    EmailPriority,
)
from utils.logger import setup_logger

logger = setup_logger("EMAIL_SERVICE")


class EmailTemplateManager:
    """Manages email templates with Jinja2"""

    def __init__(self):
        self.template_dir = email_settings.TEMPLATE_DIR
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_template(
        self, template_name: str, context: Dict[str, Any]
    ) -> Tuple[str, str]:
        """Render HTML and text templates"""
        try:
            # Render HTML template
            html_template = self.env.get_template(f"{template_name}.html")
            html_content = html_template.render(**context)

            # Try to render text template, fallback to HTML without tags
            try:
                text_template = self.env.get_template(f"{template_name}.txt")
                text_content = text_template.render(**context)
            except:
                # Simple fallback: remove HTML tags and clean up
                import re

                text_content = re.sub(r"<[^>]+>", "", html_content)
                text_content = re.sub(r"\n\s*\n", "\n\n", text_content).strip()

            return html_content, text_content

        except Exception as e:
            logger.error(f"Template rendering error for {template_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render email template: {str(e)}",
            )


class ResendEmailService:
    """Email service using Resend API"""

    def __init__(self):
        self.template_manager = EmailTemplateManager()
        resend.api_key = email_settings.RESEND_API_KEY

        # Initialize Resend client
        self.client = resend

        # Template configurations
        self.template_configs = {
            EmailType.APPOINTMENT_CONFIRMATION: {
                "template": "appointment_confirmation",
                "subject": "Appointment Confirmation - Dental Clinic",
            },
            EmailType.APPOINTMENT_REMINDER: {
                "template": "appointment_reminder",
                "subject": "Appointment Reminder - Dental Clinic",
            },
            EmailType.APPOINTMENT_CANCELLATION: {
                "template": "appointment_cancellation",
                "subject": "Appointment Cancellation - Dental Clinic",
            },
            EmailType.WELCOME_PATIENT: {
                "template": "welcome_patient",
                "subject": "Welcome to Our Dental Clinic",
            },
            EmailType.WELCOME_STAFF: {
                "template": "welcome_staff",
                "subject": "Welcome to Dental Clinic Team",
            },
            EmailType.PASSWORD_RESET: {
                "template": "password_reset",
                "subject": "Password Reset Request - Dental Clinic",
            },
            EmailType.INVOICE_SENT: {
                "template": "invoice_sent",
                "subject": "Invoice from Dental Clinic",
            },
            EmailType.PAYMENT_CONFIRMATION: {
                "template": "payment_confirmation",
                "subject": "Payment Confirmation - Dental Clinic",
            },
            EmailType.PRESCRIPTION_READY: {
                "template": "prescription_ready",
                "subject": "Prescription Ready - Dental Clinic",
            },
            EmailType.NEWSLETTER: {
                "template": "newsletter",
                "subject": "Newsletter from Dental Clinic",
            },
            EmailType.SECURITY_ALERT: {
                "template": "security_alert",
                "subject": "Security Alert - Dental Clinic",
            },
        }

    async def send_email(self, email_request: EmailRequest) -> EmailResponse:
        """Send a single email using Resend"""
        try:
            if not email_settings.SEND_EMAILS:
                logger.info(
                    f"Email sending disabled. Would send to: {email_request.to}"
                )
                return EmailResponse(
                    success=True, message_id="simulated", recipients=email_request.to
                )

            # Render templates
            html_content, text_content = self.template_manager.render_template(
                email_request.template_name, email_request.template_data
            )

            # Prepare Resend parameters
            params = {
                "from": f"{email_settings.FROM_NAME} <{email_settings.FROM_EMAIL}>",
                "to": email_request.to,
                "subject": email_request.subject,
                "html": html_content,
                "text": text_content,
            }

            # Add optional fields
            if email_request.cc:
                params["cc"] = email_request.cc
            if email_request.bcc:
                params["bcc"] = email_request.bcc
            if email_request.reply_to:
                params["reply_to"] = email_request.reply_to
            if email_request.attachments:
                params["attachments"] = [
                    {
                        "filename": attachment.filename,
                        "content": (
                            attachment.content.decode("utf-8")
                            if isinstance(attachment.content, bytes)
                            else attachment.content
                        ),
                    }
                    for attachment in email_request.attachments
                ]

            # Send email via Resend
            result = self.client.Emails.send(params)

            if email_settings.LOG_EMAILS:
                logger.info(
                    f"Email sent successfully: {result['id']} to {email_request.to}"
                )

            return EmailResponse(
                success=True, message_id=result["id"], recipients=email_request.to
            )

        except Exception as e:
            logger.error(f"Failed to send email to {email_request.to}: {str(e)}")
            return EmailResponse(
                success=False, error=str(e), recipients=email_request.to
            )

    async def send_bulk_emails(
        self, bulk_request: BulkEmailRequest
    ) -> List[EmailResponse]:
        """Send multiple emails with rate limiting"""
        results = []

        # Process in batches to avoid rate limits
        for i in range(0, len(bulk_request.emails), bulk_request.batch_size):
            batch = bulk_request.emails[i : i + bulk_request.batch_size]

            # Send emails concurrently
            batch_tasks = [self.send_email(email) for email in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Process results
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append(
                        EmailResponse(success=False, error=str(result), recipients=[])
                    )
                else:
                    results.append(result)

            # Rate limiting delay
            if i + bulk_request.batch_size < len(bulk_request.emails):
                await asyncio.sleep(1)  # 1 second between batches

        return results

    async def send_templated_email(
        self,
        email_type: EmailType,
        to: List[str],
        template_data: Dict[str, Any],
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[EmailAttachment]] = None,
    ) -> EmailResponse:
        """Send email using predefined templates"""
        template_config = self.template_configs.get(email_type)
        if not template_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown email type: {email_type}",
            )

        email_request = EmailRequest(
            to=to,
            subject=template_config["subject"],
            template_name=template_config["template"],
            template_data=template_data,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )

        return await self.send_email(email_request)

    async def send_appointment_confirmation(
        self,
        patient_email: str,
        patient_name: str,
        appointment_date: str,
        dentist_name: str,
        appointment_type: str,
        location: str = "Main Clinic",
    ) -> EmailResponse:
        """Send appointment confirmation email"""
        template_data = {
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "dentist_name": dentist_name,
            "appointment_type": appointment_type,
            "location": location,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
        }

        return await self.send_templated_email(
            EmailType.APPOINTMENT_CONFIRMATION,
            to=[patient_email],
            template_data=template_data,
        )

    async def send_appointment_reminder(
        self,
        patient_email: str,
        patient_name: str,
        appointment_date: str,
        dentist_name: str,
        days_until: int = 1,
    ) -> EmailResponse:
        """Send appointment reminder email"""
        template_data = {
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "dentist_name": dentist_name,
            "days_until": days_until,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
        }

        return await self.send_templated_email(
            EmailType.APPOINTMENT_REMINDER,
            to=[patient_email],
            template_data=template_data,
        )

    async def send_welcome_patient(
        self,
        patient_email: str,
        patient_name: str,
        temporary_password: Optional[str] = None,
    ) -> EmailResponse:
        """Send welcome email to new patient"""
        template_data = {
            "patient_name": patient_name,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
            "temporary_password": temporary_password,
            "has_password": temporary_password is not None,
        }

        return await self.send_templated_email(
            EmailType.WELCOME_PATIENT, to=[patient_email], template_data=template_data
        )

    async def send_password_reset(
        self, user_email: str, user_name: str, reset_token: str, expiry_hours: int = 24
    ) -> EmailResponse:
        """Send password reset email"""
        template_data = {
            "user_name": user_name,
            "reset_token": reset_token,
            "expiry_hours": expiry_hours,
            "clinic_name": email_settings.FROM_NAME,
        }

        return await self.send_templated_email(
            EmailType.PASSWORD_RESET, to=[user_email], template_data=template_data
        )

    async def send_invoice(
        self,
        patient_email: str,
        patient_name: str,
        invoice_number: str,
        amount: float,
        due_date: str,
        invoice_url: Optional[str] = None,
    ) -> EmailResponse:
        """Send invoice email"""
        template_data = {
            "patient_name": patient_name,
            "invoice_number": invoice_number,
            "amount": amount,
            "due_date": due_date,
            "invoice_url": invoice_url,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
        }

        return await self.send_templated_email(
            EmailType.INVOICE_SENT, to=[patient_email], template_data=template_data
        )

    async def send_payment_confirmation(
        self,
        patient_email: str,
        patient_name: str,
        invoice_number: str,
        amount_paid: float,
        payment_method: str,
    ) -> EmailResponse:
        """Send payment confirmation email"""
        template_data = {
            "patient_name": patient_name,
            "invoice_number": invoice_number,
            "amount_paid": amount_paid,
            "payment_method": payment_method,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
        }

        return await self.send_templated_email(
            EmailType.PAYMENT_CONFIRMATION,
            to=[patient_email],
            template_data=template_data,
        )

    async def verify_email(self, email: str) -> bool:
        """Verify email address using Resend"""
        try:
            # Resend doesn't have direct email verification, but we can validate format
            # For actual verification, you might want to use a dedicated service
            from email_validator import validate_email, EmailNotValidError

            try:
                validate_email(email)
                return True
            except EmailNotValidError:
                return False
        except Exception as e:
            logger.error(f"Email verification error for {email}: {e}")
            return False


# Global email service instance
email_service = ResendEmailService()
