# src/services/email_service.py
import asyncio
from typing import Dict, Any, List, Optional, Tuple
import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape
from fastapi import HTTPException, status
import os
from pathlib import Path
import time
from datetime import datetime

from core.email_config import email_settings
from schemas.email_schemas import (
    EmailRequest,
    EmailResponse,
    EmailAttachment,
    BulkEmailRequest,
    EmailType,
)
from utils.url_scheme_handler import URLSchemeHandler
from utils.logger import setup_logger
from custom_types.resend_types import ResendSendParams

logger = setup_logger("EMAIL_SERVICE")


class EmailTemplateManager:
    """Manages email templates with Jinja2"""

    def __init__(self):
        # Get the project root directory
        project_root = Path(__file__).parent.parent.parent
        self.template_dir = str(project_root / "src" / "templates" / "email")

        # Ensure template directory exists
        if not os.path.exists(self.template_dir):
            logger.warning(f"Template directory not found: {self.template_dir}")
            # Create fallback directory
            os.makedirs(self.template_dir, exist_ok=True)

        logger.info(f"Loading email templates from: {self.template_dir}")

        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Log available templates
        available_templates = self.env.list_templates()
        logger.info(f"Available email templates: {available_templates}")

    def template_exists(self, template_name: str) -> bool:
        """Check if a template exists"""
        try:
            template_path = f"{template_name}.html"
            self.env.get_template(template_path)
            return True
        except Exception:
            return False

    def render_template(
        self, template_name: str, context: Dict[str, Any]
    ) -> Tuple[str, str]:
        """Render HTML and text templates"""
        try:
            # Check if template exists
            template_path = f"{template_name}.html"
            if not self.template_exists(template_name):
                logger.error(f"Template not found: {template_path}")
                logger.error(f"Available templates: {self.env.list_templates()}")
                raise FileNotFoundError(
                    f"Template '{template_path}' not found in {self.template_dir}"
                )

            # Render HTML template
            html_template = self.env.get_template(template_path)
            html_content = html_template.render(**context)

            # Try to render text template, fallback to HTML without tags
            text_template_path = f"{template_name}.txt"
            text_content = ""
            try:
                text_template = self.env.get_template(text_template_path)
                text_content = text_template.render(**context)
            except Exception:
                # Simple fallback: remove HTML tags and clean up
                import re

                text_content = re.sub(r"<[^>]+>", "", html_content)
                text_content = re.sub(r"\n\s*\n", "\n\n", text_content).strip()

            return html_content, text_content

        except FileNotFoundError as e:
            logger.error(f"Template file not found: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Email template not found: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Template rendering error for {template_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render email template: {str(e)}",
            )


class ResendEmailService:
    """Email service using Resend API with proper typing"""

    def __init__(self):
        self.template_manager = EmailTemplateManager()
        resend.api_key = email_settings.RESEND_API_KEY
        self.client = resend

        # Enhanced retry configuration
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        self.timeout = 30  # seconds

        # Network health tracking
        self.last_success = None
        self.consecutive_failures = 0
        self.max_consecutive_failures = 10

        # Template configurations
        self.template_configs = {
            EmailType.TEST_EMAIL: {
                "template": "test_email",
                "subject": "Testing Email service",
            },
            EmailType.CUSTOM_EMAIL: {"template": "custom_email", "subject": ""},
            EmailType.WELCOME_TENANT: {
                "template": "welcome_tenant",
                "subject": "Welcome to KwantaBit Dental Clinic Management Suite - Your Default Admin Credentials",
            },
            EmailType.EMAIL_VERIFICATION: {
                "template": "email_verification",
                "subject": "Email Verification - Dental Clinic",
            },
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

        self._validate_templates()

    def _validate_templates(self) -> Dict[str, bool]:
        """Validate that all required templates exist"""
        try:
            validation_results = {}

            for email_type, config in self.template_configs.items():
                template_name = config["template"]
                html_exists = self.template_manager.template_exists(template_name)
                validation_results[email_type.value] = html_exists

                if not html_exists:
                    logger.warning(
                        f"Missing template for {email_type}: {template_name}.html"
                    )
                else:
                    logger.info(
                        f"✓ Template found: {template_name}.html for {email_type}"
                    )

            # Log summary
            total_templates = len(validation_results)
            found_templates = sum(validation_results.values())
            logger.info(
                f"Template validation: {found_templates}/{total_templates} templates found"
            )

            return validation_results

        except Exception as e:
            logger.error(f"Template validation failed: {e}")
            return {}

    def _prepare_resend_params(
        self, email_request: EmailRequest, html_content: str, text_content: str
    ) -> ResendSendParams:
        """Prepare properly typed parameters for Resend API"""
        params: ResendSendParams = {
            "from": f"{email_settings.FROM_NAME} <{email_settings.FROM_EMAIL}>",
            "to": email_request.to,
            "subject": email_request.subject,
            "html": html_content,
            "text": text_content,
        }

        # Add optional fields with proper typing
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
                        else str(attachment.content)
                    ),
                }
                for attachment in email_request.attachments
            ]

        return params

    async def send_email(self, email_request: EmailRequest) -> EmailResponse:
        """Send a single email using Resend with robust error handling"""
        # Check if we should skip due to too many failures
        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.warning(
                f"Skipping email to {email_request.to} due to {self.consecutive_failures} consecutive failures"
            )
            return EmailResponse(
                success=False,
                error="Email service temporarily unavailable due to network issues",
                recipients=email_request.to,
            )

        if not email_settings.SEND_EMAILS:
            logger.info(f"Email sending disabled. Would send to: {email_request.to}")
            return EmailResponse(
                success=True, message_id="simulated", recipients=email_request.to
            )

        for attempt in range(self.max_retries):
            try:
                # Render templates
                html_content, text_content = self.template_manager.render_template(
                    email_request.template_name, email_request.template_data
                )

                # Prepare properly typed Resend parameters
                params = self._prepare_resend_params(
                    email_request, html_content, text_content
                )

                # Send email via Resend with timeout - use proper async execution
                def send_email_sync():
                    return self.client.Emails.send(params)

                # Execute the sync function in a thread pool
                result = await asyncio.get_event_loop().run_in_executor(
                    None, send_email_sync
                )

                # Success - update health tracking
                self.last_success = datetime.now()
                self.consecutive_failures = 0

                if email_settings.LOG_EMAILS:
                    logger.info(
                        f"Email sent successfully: {result['id']} to {email_request.to}"
                    )

                return EmailResponse(
                    success=True, message_id=result["id"], recipients=email_request.to
                )

            except asyncio.TimeoutError:
                logger.warning(
                    f"Email send timeout (attempt {attempt + 1}/{self.max_retries}) to {email_request.to}"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue

            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    f"Email send failed (attempt {attempt + 1}/{self.max_retries}) to {email_request.to}: {error_msg}"
                )

                # Update failure tracking
                self.consecutive_failures += 1

                # Check for specific error types
                if (
                    "NameResolutionError" in error_msg
                    or "getaddrinfo failed" in error_msg
                ):
                    logger.error(
                        f"DNS resolution failed for Resend API. Check internet connection."
                    )
                    break  # Don't retry DNS errors
                elif "Connection" in error_msg or "Network" in error_msg:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    # Other errors might be retryable
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)
                    continue

        # All retries failed
        final_error = f"Failed to send email after {self.max_retries} attempts"
        logger.error(f"{final_error} to {email_request.to}")
        return EmailResponse(
            success=False, error=final_error, recipients=email_request.to
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
        """Send email using predefined templates with enhanced logging"""
        template_config = self.template_configs.get(email_type)
        if not template_config:
            logger.error(f"Unknown email type: {email_type}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown email type: {email_type}",
            )

        logger.info(f"Preparing {email_type.value} email for {to}")

        email_request = EmailRequest(
            to=to,
            subject=template_config["subject"],
            template_name=template_config["template"],
            template_data=template_data,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )

        response = await self.send_email(email_request)

        if response.success:
            logger.info(f"Successfully sent {email_type.value} email to {to}")
        else:
            logger.error(
                f"Failed to send {email_type.value} email to {to}: {response.error}"
            )

        return response

    async def check_connectivity(self) -> Dict[str, Any]:
        """Check email service connectivity"""
        try:
            # Simple check by attempting to resolve the Resend API hostname
            import socket

            start_time = time.time()
            socket.gethostbyname("api.resend.com")
            dns_time = time.time() - start_time

            return {
                "dns_resolution": True,
                "dns_response_time": round(dns_time * 1000, 2),  # ms
                "api_key_configured": bool(
                    email_settings.RESEND_API_KEY
                    and email_settings.RESEND_API_KEY != "my_secret_key"
                ),
                "last_success": (
                    self.last_success.isoformat() if self.last_success else None
                ),
                "consecutive_failures": self.consecutive_failures,
                "service_status": (
                    "healthy" if self.consecutive_failures == 0 else "degraded"
                ),
            }
        except socket.gaierror as e:
            logger.error(f"DNS resolution failed for Resend API: {e}")
            return {
                "dns_resolution": False,
                "error": f"DNS resolution failed: {str(e)}",
                "api_key_configured": bool(
                    email_settings.RESEND_API_KEY
                    and email_settings.RESEND_API_KEY != "my_secret_key"
                ),
                "consecutive_failures": self.consecutive_failures,
                "service_status": "unavailable",
            }
        except Exception as e:
            logger.error(f"Connectivity check failed: {e}")
            return {
                "dns_resolution": False,
                "error": str(e),
                "consecutive_failures": self.consecutive_failures,
                "service_status": "unknown",
            }

    async def send_tenant_welcome_email(
        self, user_email: str, user_name: str, temp_password: str, tenant_slug: str
    ) -> EmailResponse:
        """Send tenant welcome email with fallback to logging"""
        try:
            # Create deep link for one-click login
            deep_link = f"{URLSchemeHandler.SCHEME}://login?tenant={tenant_slug}"

            # Create a clickable link that works across different platforms
            clickable_link = f"""
            <a href="{deep_link}" style="text-decoration: none; color: white; background: linear-gradient(135deg, #10b981, #059669); padding: 14px 28px; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px;">
                Launch Dental Clinic Application
            </a>
            """

            # Also include a fallback URL for web browsers
            web_fallback_url = (
                f"https://app.kwantabit-dental.com/launch?tenant={tenant_slug}"
            )

            template_data = {
                "user_name": user_name,
                "user_email": user_email,
                "temporary_password": temp_password,
                "tenant_slug": tenant_slug,
                "deep_link_url": deep_link,
                "clickable_link": clickable_link,  # Add this for HTML template
                "web_fallback_url": web_fallback_url,  # Add web fallback
                "clinic_name": email_settings.FROM_NAME,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "support_email": email_settings.FROM_EMAIL,
                "setup_guide_url": email_settings.SETUP_GUIDE_URL,
                "download_url": email_settings.DOWNLOAD_URL,
            }

            response = await self.send_templated_email(
                EmailType.WELCOME_TENANT,
                to=[user_email],
                template_data=template_data,
            )

            # If email fails, log the credentials for manual recovery
            if not response.success:
                logger.warning(
                    f"EMAIL FAILED - Tenant welcome email could not be sent to {user_email}. "
                    f"Manual intervention required. Credentials: "
                    f"Email: {user_email}, Temp Password: {temp_password}, "
                    f"Tenant: {tenant_slug}"
                )

            return response

        except Exception as e:
            logger.error(f"Failed to prepare tenant welcome email: {e}")
            # Still return a response indicating failure
            return EmailResponse(
                success=False,
                error=f"Failed to prepare email: {str(e)}",
                recipients=[user_email],
            )

    async def send_password_reset(
        self, user_email: str, user_name: str, reset_token: str, expiry_hours: int = 24
    ) -> EmailResponse:
        """Send password reset email with deep link"""
        try:

            # Create deep link for password reset
            deep_link = URLSchemeHandler.create_deep_link(
                "reset-password", token=reset_token
            )

            # Create a clickable link with proper styling for email
            clickable_link = f"""
            <a href="{deep_link}" class="button" style="text-decoration: none; color: white; background: linear-gradient(135deg, #ef4444, #dc2626); padding: 14px 28px; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; border: none; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.3);">
                🔒 Reset Password in Application
            </a>
            """

            # Create a web fallback URL for browsers that don't support deep links
            web_fallback_url = (
                f"https://app.kwantabit-dental.com/reset-password?token={reset_token}"
            )

            template_data = {
                "user_name": user_name,
                "reset_token": reset_token,
                "deep_link_url": deep_link,
                "clickable_link": clickable_link,
                "web_fallback_url": web_fallback_url,
                "expiry_hours": expiry_hours,
                "clinic_name": email_settings.FROM_NAME,
            }

            # Log the password reset attempt for security audit
            logger.info(
                f"Password reset email prepared for {user_email}. "
                f"Deep link: {deep_link}, Expires in: {expiry_hours} hours"
            )

            return await self.send_templated_email(
                EmailType.PASSWORD_RESET,
                to=[user_email],
                template_data=template_data,
            )

        except Exception as e:
            logger.error(f"Failed to prepare password reset email: {e}")
            # Still return a response indicating failure
            return EmailResponse(
                success=False,
                error=f"Failed to prepare password reset email: {str(e)}",
                recipients=[user_email],
            )

    async def send_password_reset_v2(
        self,
        user_email: str,
        user_name: str,
        reset_token: str,
        tenant_slug: str = None,
        user_agent: str = None,
        ip_address: str = None,
        expiry_hours: int = 24,
    ) -> EmailResponse:
        """Enhanced password reset email with security context and multi-platform support"""
        try:
            # Create deep link with security context
            deep_link_params = {"token": reset_token}
            if tenant_slug:
                deep_link_params["tenant"] = tenant_slug
            if user_agent:
                # Hash user agent for privacy
                import hashlib

                user_agent_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:8]
                deep_link_params["context"] = user_agent_hash

            deep_link = URLSchemeHandler.create_deep_link(
                "reset-password", **deep_link_params
            )

            # Create platform-specific instructions
            platform_info = (
                self._detect_platform_from_user_agent(user_agent)
                if user_agent
                else None
            )

            template_data = {
                "user_name": user_name,
                "reset_token": reset_token,
                "deep_link_url": deep_link,
                "expiry_hours": expiry_hours,
                "clinic_name": email_settings.FROM_NAME,
                "support_email": email_settings.SUPPORT_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "tenant_slug": tenant_slug if tenant_slug else "your clinic",
                "has_tenant": tenant_slug is not None,
                "ip_address": ip_address if ip_address else "Not available",
                "request_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "platform": platform_info,
                "security_context": {
                    "token_length": len(reset_token),
                    "token_type": "JWT" if len(reset_token) > 100 else "Simple",
                    "requires_tenant": tenant_slug is not None,
                },
            }

            # Security logging
            logger.info(
                f"Enhanced password reset for {user_email}. "
                f"Platform: {platform_info}, IP: {ip_address}, "
                f"Expires: {expiry_hours}h, Tenant: {tenant_slug}"
            )

            return await self.send_templated_email(
                EmailType.PASSWORD_RESET,
                to=[user_email],
                template_data=template_data,
            )

        except Exception as e:
            logger.error(f"Enhanced password reset email failed: {e}")
            # Fall back to simple password reset
            return await self.send_password_reset(
                user_email, user_name, reset_token, expiry_hours
            )

    def _detect_platform_from_user_agent(self, user_agent: str) -> Dict[str, Any]:
        """Detect platform from user agent string"""
        try:
            result = {
                "device": "Unknown",
                "os": "Unknown",
                "browser": "Unknown",
                "is_mobile": False,
                "is_desktop": False,
            }

            user_agent = user_agent.lower()

            # Detect OS
            if "windows" in user_agent:
                result["os"] = "Windows"
                result["is_desktop"] = True
            elif "mac" in user_agent:
                result["os"] = "macOS"
                result["is_desktop"] = True
            elif "linux" in user_agent:
                result["os"] = "Linux"
                result["is_desktop"] = True
            elif "android" in user_agent:
                result["os"] = "Android"
                result["is_mobile"] = True
            elif "iphone" in user_agent or "ipad" in user_agent:
                result["os"] = "iOS"
                result["is_mobile"] = True

            # Detect browser
            if "chrome" in user_agent and "edg" not in user_agent:
                result["browser"] = "Chrome"
            elif "firefox" in user_agent:
                result["browser"] = "Firefox"
            elif "safari" in user_agent and "chrome" not in user_agent:
                result["browser"] = "Safari"
            elif "edg" in user_agent:
                result["browser"] = "Edge"

            # Detect device type
            if "mobile" in user_agent:
                result["device"] = "Mobile"
                result["is_mobile"] = True
            elif "tablet" in user_agent:
                result["device"] = "Tablet"
                result["is_mobile"] = True
            else:
                result["device"] = "Desktop"
                result["is_desktop"] = True

            return result

        except Exception:
            return {
                "device": "Unknown",
                "os": "Unknown",
                "browser": "Unknown",
                "is_mobile": False,
                "is_desktop": False,
            }

    async def send_email_verification(
        self, user_email: str, user_name: str, verification_token: str
    ) -> EmailResponse:
        """Send email verification with deep link"""
        deep_link = URLSchemeHandler.create_deep_link(
            "verify-email", token=verification_token
        )

        template_data = {
            "user_name": user_name,
            "verification_token": verification_token,
            "deep_link_url": deep_link,
            "clinic_name": email_settings.FROM_NAME,
        }

        return await self.send_templated_email(
            EmailType.EMAIL_VERIFICATION,
            to=[user_email],
            template_data=template_data,
        )

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

    async def send_welcome_staff(
        self,
        staff_email: str,
        staff_name: str,
        staff_role: str,
        clinic_name: str,
        clinic_slug: str,
        clinic_address: str,
        manager_name: str,
        manager_email: str,
        office_hours: str,
        temporary_password: Optional[str] = None,
    ) -> EmailResponse:
        """Send welcome email to new staff member"""
        try:
            # Create deep link for one-click login
            deep_link = URLSchemeHandler.create_deep_link("login", tenant=clinic_slug)

            template_data = {
                "staff_name": staff_name,
                "staff_email": staff_email,
                "staff_role": staff_role,
                "clinic_name": clinic_name,
                "clinic_slug": clinic_slug,
                "clinic_address": clinic_address,
                "manager_name": manager_name,
                "manager_email": manager_email,
                "temporary_password": temporary_password,
                "deep_link_url": deep_link,
                "support_email": email_settings.FROM_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "training_guide_url": email_settings.SETUP_GUIDE_URL,
                "office_hours": office_hours,
            }

            response = await self.send_templated_email(
                EmailType.WELCOME_STAFF,
                to=[staff_email],
                template_data=template_data,
            )

            # If email fails, log the credentials for manual recovery
            if not response.success:
                logger.warning(
                    f"STAFF WELCOME EMAIL FAILED - Could not send to {staff_email}. "
                    f"Manual intervention required. Staff: {staff_name}, Role: {staff_role}, "
                    f"Clinic: {clinic_name}"
                )

            return response

        except Exception as e:
            logger.error(f"Failed to prepare staff welcome email: {e}")
            return EmailResponse(
                success=False,
                error=f"Failed to prepare staff welcome email: {str(e)}",
                recipients=[staff_email],
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

    async def send_test_email(
        self, to_email: str, test_type: str = "connectivity"
    ) -> EmailResponse:
        """Send a test email to verify email service functionality"""
        try:
            logger.info(
                f"Sending test email to {to_email} for {test_type} verification"
            )

            # Test template data
            template_data = {
                "test_type": test_type,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "clinic_name": email_settings.FROM_NAME,
                "support_email": email_settings.SUPPORT_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "service_status": "operational",
                "test_details": {
                    "recipient": to_email,
                    "purpose": f"Email service {test_type} test",
                    "environment": (
                        "production" if email_settings.SEND_EMAILS else "development"
                    ),
                },
            }

            # Use a simple test template or fallback to welcome template
            if self.template_manager.template_exists("test_email"):
                template_name = "test_email"
                subject = f"✓ Email Service Test - {test_type.title()}"
            else:
                template_name = "welcome_tenant"
                subject = f"Email Service Test - {test_type.title()}"
                template_data.update(
                    {
                        "user_name": "Test Recipient",
                        "user_email": to_email,
                        "temporary_password": "test-password-123",
                        "tenant_slug": "test-tenant",
                        "deep_link_url": "kwantabit-dental://test",
                        "setup_guide_url": email_settings.SETUP_GUIDE_URL,
                        "download_url": email_settings.DOWNLOAD_URL,
                    }
                )

            email_request = EmailRequest(
                to=[to_email],
                subject=subject,
                template_name=template_name,
                template_data=template_data,
            )

            response = await self.send_email(email_request)

            # Log test results
            if response.success:
                logger.info(
                    f"✅ Test email sent successfully to {to_email}. Message ID: {response.message_id}"
                )
            else:
                logger.error(f"❌ Test email failed to {to_email}: {response.error}")

            return response

        except Exception as e:
            logger.error(f"Test email preparation failed: {e}")
            return EmailResponse(
                success=False,
                error=f"Test email preparation failed: {str(e)}",
                recipients=[to_email],
            )

    async def verify_service_health(self) -> Dict[str, Any]:
        """Comprehensive email service health verification"""
        health_check = await self.check_connectivity()

        # Test data for comprehensive health check
        test_results = {
            "connectivity": health_check,
            "templates_available": list(self.template_configs.keys()),
            "configuration": {
                "from_email": email_settings.FROM_EMAIL,
                "from_name": email_settings.FROM_NAME,
                "send_emails_enabled": email_settings.SEND_EMAILS,
                "log_emails_enabled": email_settings.LOG_EMAILS,
                "api_key_configured": bool(
                    email_settings.RESEND_API_KEY
                    and email_settings.RESEND_API_KEY != "my_secret_key"
                ),
            },
            "service_status": "unknown",
        }

        # Check template availability
        template_health = {}
        for email_type, config in self.template_configs.items():
            template_name = config["template"]
            exists = self.template_manager.template_exists(template_name)
            template_health[email_type.value] = {
                "template": template_name,
                "exists": exists,
                "subject": config["subject"],
            }

        test_results["template_health"] = template_health

        # Determine overall status
        if not health_check.get("dns_resolution", False):
            test_results["service_status"] = "unavailable"
        elif not test_results["configuration"]["api_key_configured"]:
            test_results["service_status"] = "misconfigured"
        elif self.consecutive_failures > 0:
            test_results["service_status"] = "degraded"
        else:
            test_results["service_status"] = "healthy"

        return test_results

    async def validate_password_reset_token(
        self, token: str, expected_email: str = None
    ) -> Dict[str, Any]:
        """Validate password reset token (simplified version for email service)"""
        try:
            # In a real implementation, you would validate against your auth service
            # This is a simplified version for demonstration
            import jwt

            # Check token format
            if len(token) < 20:
                return {"valid": False, "error": "Token too short", "can_retry": True}

            # Check if token looks like a JWT
            if len(token) > 100 and token.count(".") == 2:
                # Try to decode JWT
                try:
                    # This would normally use your SECRET_KEY
                    # decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                    return {
                        "valid": True,
                        "type": "JWT",
                        "expires_in": 3600,  # Example: 1 hour
                        "email": expected_email if expected_email else "unknown",
                        "can_reset": True,
                    }
                except jwt.ExpiredSignatureError:
                    return {"valid": False, "error": "Token expired", "can_retry": True}
                except jwt.InvalidTokenError:
                    return {
                        "valid": False,
                        "error": "Invalid token",
                        "can_retry": False,
                    }

            # Simple token validation
            return {
                "valid": True,
                "type": "Simple",
                "expires_in": 86400,  # 24 hours
                "email": expected_email if expected_email else "unknown",
                "can_reset": True,
            }

        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return {
                "valid": False,
                "error": f"Validation error: {str(e)}",
                "can_retry": False,
            }

    async def send_password_reset_success(
        self,
        user_email: str,
        user_name: str,
        device_info: Dict[str, Any] = None,
        ip_address: str = None,
    ) -> EmailResponse:
        """Send notification that password was successfully reset"""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

            template_data = {
                "user_name": user_name,
                "reset_time": current_time,
                "clinic_name": email_settings.FROM_NAME,
                "support_email": email_settings.SUPPORT_EMAIL,
                "device_info": (
                    device_info if device_info else {"type": "Unknown device"}
                ),
                "ip_address": ip_address if ip_address else "Not available",
                "security_tips": [
                    "Use a unique password for this account",
                    "Enable two-factor authentication",
                    "Review recent login activity",
                    "Log out of unused devices",
                ],
            }

            logger.info(f"Password reset success notification sent to {user_email}")

            return await self.send_templated_email(
                EmailType.SECURITY_ALERT,  # You might want to create a specific template for this
                to=[user_email],
                template_data=template_data,
            )

        except Exception as e:
            logger.error(f"Failed to send password reset success email: {e}")
            return EmailResponse(
                success=False,
                error=f"Failed to send success notification: {str(e)}",
                recipients=[user_email],
            )


# Global email service instance
email_service = ResendEmailService()
