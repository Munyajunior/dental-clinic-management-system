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
import socket

from core.email_config import email_settings
from schemas.email_schemas import (
    EmailRequest,
    EmailResponse,
    EmailAttachment,
    BulkEmailRequest,
    EmailType,
)
from utils.logger import setup_logger
from custom_types.resend_types import ResendSendParams
from utils.url_scheme_handler import URLSchemeHandler

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
            template_path = (
                template_name
                if template_name.endswith(".html")
                else f"{template_name}.html"
            )
            self.env.get_template(template_path)
            return True
        except Exception:
            # Also try without extension
            try:
                self.env.get_template(template_name)
                return True
            except Exception as e:
                logger.debug(f"Template {template_name} not found: {e}")
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

    def get_template_path(self, template_name: str) -> Optional[str]:
        """Get the full path to a template file"""
        try:
            template_path = os.path.join(self.template_dir, f"{template_name}.html")
            if os.path.exists(template_path):
                return template_path
            return None
        except Exception:
            return None


class ResendEmailService:
    """Email service using Resend API with proper typing"""

    def __init__(self):
        self.template_manager = EmailTemplateManager()
        resend.api_key = email_settings.RESEND_API_KEY
        self.client = resend

        # URL scheme handler for creating deep links
        self.url_handler = URLSchemeHandler()

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
                "subject": "Welcome to KwantaDent Dental Clinic Management Suite - Your Default Admin Credentials",
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

                # Debug: Log what we're looking for
                logger.debug(f"Checking template for {email_type}: {template_name}")

                html_exists = self.template_manager.template_exists(template_name)
                validation_results[email_type.value] = html_exists

                if not html_exists:
                    logger.warning(
                        f"Missing template for {email_type}: {template_name}.html"
                    )
                    # Try to find the actual file
                    template_path = self.template_manager.get_template_path(
                        template_name
                    )
                    if template_path and os.path.exists(template_path):
                        logger.warning(f"  File actually exists at: {template_path}")
                        logger.warning(
                            f"  File size: {os.path.getsize(template_path)} bytes"
                        )
                        # Check file permissions
                        try:
                            with open(template_path, "r", encoding="utf-8") as f:
                                content = f.read(100)  # Read first 100 chars
                                logger.warning(f"  File starts with: {content}")
                        except Exception as read_err:
                            logger.warning(f"  Cannot read file: {read_err}")
                    else:
                        logger.warning(f"  File not found on disk")
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

            # Log missing templates
            missing = [k for k, v in validation_results.items() if not v]
            if missing:
                logger.warning(f"Missing templates: {missing}")
                # Provide helpful suggestion
                logger.warning(
                    f"Check if these files exist in: {self.template_manager.template_dir}"
                )
                logger.warning(
                    f"Expected files: {[f'{name}.html' for name in missing]}"
                )

            return validation_results

        except (
            Exception
        ) as validation_error:  # Fixed: Changed variable name from 'e' to 'validation_error'
            logger.error(
                f"Template validation failed: {validation_error}", exc_info=True
            )
            # Try to provide more context
            try:
                logger.error(
                    f"Template directory: {self.template_manager.template_dir}"
                )
                if os.path.exists(self.template_manager.template_dir):
                    files = os.listdir(self.template_manager.template_dir)
                    logger.error(f"Files in directory: {files}")
                else:
                    logger.error(f"Template directory does not exist!")
            except Exception as dir_error:
                logger.error(f"Cannot list directory: {dir_error}")
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
                        "DNS resolution failed for Resend API. Check internet connection."
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
        """Send tenant welcome email with deep link for one-click login"""
        try:
            # Create deep link for one-click login
            deep_link = self.url_handler.create_deep_link("login", tenant=tenant_slug)

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

            # Include instructions for first-time users
            app_instructions = self._get_app_launch_instructions()

            template_data = {
                "user_name": user_name,
                "user_email": user_email,
                "temporary_password": temp_password,
                "tenant_slug": tenant_slug,
                "deep_link_url": deep_link,
                "clickable_link": clickable_link,
                "web_fallback_url": web_fallback_url,
                "app_instructions": app_instructions,
                "scheme_name": email_settings.SCHEME,
                "app_name": email_settings.APP_NAME,
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
                    f"Tenant: {tenant_slug}, Deep Link: {deep_link}"
                )

            return response

        except Exception as e:
            logger.error(f"Failed to prepare tenant welcome email: {e}")
            return EmailResponse(
                success=False,
                error=f"Failed to prepare email: {str(e)}",
                recipients=[user_email],
            )

    def _get_app_launch_instructions(self) -> str:
        """Get application launch instructions for email templates"""
        return f"""
        <p><strong>How to launch the application:</strong></p>
        <ol>
            <li><strong>One-click launch:</strong> Click the "Launch Dental Clinic Application" button above</li>
            <li><strong>If prompted:</strong> Allow the application to open</li>
            <li><strong>First time?</strong> The application will be installed automatically</li>
            <li><strong>Manual launch:</strong> Copy and paste this link into your browser: <code>{email_settings.SCHEME}://login</code></li>
        </ol>
        <p><strong>Note:</strong> On first use, your system may ask for permission to open the application. 
        This is normal and required for the application to function properly.</p>
        """

    async def send_password_reset(
        self, user_email: str, user_name: str, reset_token: str, expiry_hours: int = 24
    ) -> EmailResponse:
        """Send password reset email with deep link"""
        try:
            # Create deep link for password reset
            deep_link = self.url_handler.create_deep_link(
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

            # Include reset instructions
            reset_instructions = f"""
            <p><strong>Password Reset Instructions:</strong></p>
            <ol>
                <li>Click the "Reset Password" button above</li>
                <li>If prompted, allow "{email_settings.APP_NAME}" to open</li>
                <li>Enter your new password in the application</li>
                <li>Click "Update Password" to complete the reset</li>
            </ol>
            <p><strong>Note:</strong> This link expires in {expiry_hours} hours for security.</p>
            <p>If the button doesn't work, copy and paste this link into your browser: <code>{deep_link}</code></p>
            """

            current_datetime = datetime.now()

            template_data = {
                "user_name": user_name,
                "reset_token": reset_token,
                "deep_link_url": deep_link,
                "clickable_link": clickable_link,
                "web_fallback_url": web_fallback_url,
                "reset_instructions": reset_instructions,
                "expiry_hours": expiry_hours,
                "app_name": email_settings.APP_NAME,
                "scheme_name": email_settings.SCHEME,
                "clinic_name": email_settings.FROM_NAME,
                "current_year": current_datetime.year,
                "now": current_datetime,
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
        tenant_name: str = None,
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

            deep_link = self.url_handler.create_deep_link(
                "reset-password", **deep_link_params
            )

            clickable_link = f"""
                <a href="{deep_link}" class="button" style="text-decoration: none; color: white; background: linear-gradient(135deg, #ef4444, #dc2626); padding: 14px 28px; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; border: none; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.3);">
                    🔒 Reset Password in Application
                </a>
                """

            # Create platform-specific instructions
            platform_info = (
                self._detect_platform_from_user_agent(user_agent)
                if user_agent
                else None
            )

            # Get platform-specific instructions
            platform_instructions = self._get_platform_instructions(platform_info)
            current_datetime = datetime.now()

            template_data = {
                "user_name": user_name,
                "reset_token": reset_token,
                "deep_link_url": deep_link,
                "clickable_link": clickable_link,
                "expiry_hours": expiry_hours,
                "clinic_name": tenant_name,
                "support_email": email_settings.SUPPORT_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "tenant_slug": tenant_slug if tenant_slug else "your clinic",
                "has_tenant": tenant_slug is not None,
                "ip_address": ip_address if ip_address else "Not available",
                "request_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "platform": platform_info,
                "platform_instructions": platform_instructions,
                "scheme_name": email_settings.SCHEME,
                "app_name": email_settings.APP_NAME,
                "current_year": current_datetime.year,
                "now": current_datetime,
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
                f"Expires: {expiry_hours}h, Tenant: {tenant_slug}, "
                f"Deep Link: {deep_link}"
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

    def _get_platform_instructions(self, platform_info: Dict[str, Any]) -> str:
        """Get platform-specific instructions for launching the app"""
        if not platform_info:
            return "Click the link to reset your password in the application."

        device_type = platform_info.get("device", "Unknown")
        os_type = platform_info.get("os", "Unknown")

        if device_type == "Mobile" or device_type == "Tablet":
            return f"""
            <p><strong>On your {os_type} device:</strong></p>
            <ol>
                <li>Tap the "Reset Password" link</li>
                <li>If prompted, tap "Open in {email_settings.APP_NAME}"</li>
                <li>If you don't have the app installed, you'll be prompted to download it</li>
                <li>Follow the in-app instructions to reset your password</li>
            </ol>
            """
        else:  # Desktop
            return f"""
            <p><strong>On your {os_type} computer:</strong></p>
            <ol>
                <li>Click the "Reset Password" link</li>
                <li>If prompted, allow "{email_settings.APP_NAME}" to open</li>
                <li>If you don't have the app installed, it will be installed automatically</li>
                <li>Follow the in-app instructions to reset your password</li>
            </ol>
            """

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
        self,
        user_email: str,
        user_name: str,
        verification_token: str,
        user_agent: str = None,
    ) -> EmailResponse:
        """Send email verification with deep link"""
        deep_link = self.url_handler.create_deep_link(
            "verify-email", token=verification_token
        )

        # Create verification instructions
        verification_instructions = f"""
        <p><strong>Email Verification Instructions:</strong></p>
        <ol>
            <li>Click the verification link below</li>
            <li>Allow "{email_settings.APP_NAME}" to open if prompted</li>
            <li>Your email will be verified automatically</li>
            <li>You can then log in to your account</li>
        </ol>
        <p>If the link doesn't work, copy and paste this into your browser: <code>{deep_link}</code></p>
        """
        # Create platform-specific instructions
        platform_info = (
            self._detect_platform_from_user_agent(user_agent) if user_agent else None
        )

        # Get platform-specific instructions
        platform_instructions = self._get_platform_instructions(platform_info)

        template_data = {
            "user_name": user_name,
            "verification_token": verification_token,
            "deep_link_url": deep_link,
            "verification_instructions": verification_instructions,
            "app_name": email_settings.APP_NAME,
            "app_version": self.url_handler.APP_VERSION,
            "platform_instructions": platform_instructions,
            "current_year": datetime.now().year,
            "scheme_name": email_settings.SCHEME,
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
        appointment_id: str = None,
    ) -> EmailResponse:
        """Send appointment confirmation email with optional deep link"""
        template_data = {
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "dentist_name": dentist_name,
            "appointment_type": appointment_type,
            "location": location,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
            "patient_email": patient_email,
            "current_year": datetime.now().year,
        }

        # Add deep link if appointment ID is provided
        if appointment_id:
            deep_link = self.url_handler.create_deep_link(
                "open-appointment", id=appointment_id
            )
            template_data.update(
                {
                    "deep_link_url": deep_link,
                    "has_deep_link": True,
                    "app_name": email_settings.APP_NAME,
                    "appointment_id": appointment_id,
                }
            )
        else:
            template_data.update(
                {
                    "has_deep_link": False,
                }
            )

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
        appointment_id: str = None,
    ) -> EmailResponse:
        """Send appointment reminder email with optional deep link"""
        template_data = {
            "patient_name": patient_name,
            "appointment_date": appointment_date,
            "dentist_name": dentist_name,
            "days_until": days_until,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
            "current_year": datetime.now().year,
        }

        # Add deep link if appointment ID is provided
        if appointment_id:
            deep_link = self.url_handler.create_deep_link(
                "open-appointment", id=appointment_id
            )
            template_data.update(
                {
                    "deep_link_url": deep_link,
                    "has_deep_link": True,
                    "app_name": email_settings.APP_NAME,
                    "scheme_name": email_settings.SCHEME,
                }
            )
        else:
            template_data.update(
                {
                    "has_deep_link": False,
                }
            )

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
        """Send welcome email to new staff member with deep link"""
        try:
            # Create deep link for one-click login
            deep_link = self.url_handler.create_deep_link("login", tenant=clinic_slug)

            # Create staff-specific instructions
            staff_instructions = f"""
            <p><strong>Getting Started:</strong></p>
            <ol>
                <li>Click the launch button below to open the application</li>
                <li>Log in with your email and temporary password</li>
                <li>You'll be prompted to set a new password on first login</li>
                <li>Complete your profile setup</li>
                <li>Review the training materials provided</li>
            </ol>
            <p>If you need assistance, contact {manager_name} at {manager_email} or use our WhatsApp support.</p>
            """

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
                "staff_instructions": staff_instructions,
                "support_email": email_settings.FROM_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "training_guide_url": email_settings.SETUP_GUIDE_URL,
                "office_hours": office_hours,
                "app_name": email_settings.APP_NAME,
                "scheme_name": email_settings.SCHEME,
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
                    f"Clinic: {clinic_name}, Deep Link: {deep_link}"
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
        clinic_slug: Optional[str] = None,
    ) -> EmailResponse:
        """Send welcome email to new patient with optional deep link"""
        template_data = {
            "patient_name": patient_name,
            "clinic_name": email_settings.FROM_NAME,
            "contact_email": email_settings.FROM_EMAIL,
            "temporary_password": temporary_password,
            "has_password": temporary_password is not None,
        }

        # Add deep link if clinic slug is provided
        if clinic_slug:
            deep_link = self.url_handler.create_deep_link("login", tenant=clinic_slug)
            template_data.update(
                {
                    "deep_link_url": deep_link,
                    "has_deep_link": True,
                    "app_name": email_settings.APP_NAME,
                    "patient_instructions": """
                <p>You can access your patient portal by clicking the link above. 
                Use your email and temporary password to log in.</p>
                """,
                }
            )
        else:
            template_data.update(
                {
                    "has_deep_link": False,
                    "patient_instructions": f"""
                <p>You can access your patient portal by visiting our clinic website 
                or contacting us at {email_settings.FROM_EMAIL}.</p>
                """,
                }
            )

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
        self, to_email: str, test_type: str = "connectivity", test_tenant: bool = False
    ) -> EmailResponse:
        """Send a test email to verify email service functionality"""
        try:
            logger.info(
                f"Sending test email to {to_email} for {test_type} verification"
            )

            # Create a test deep link
            test_deep_link = self.url_handler.create_deep_link(
                "login", tenant="test-clinic"
            )

            # Test template data
            template_data = {
                "test_type": test_type,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "clinic_name": email_settings.FROM_NAME,
                "support_email": email_settings.SUPPORT_EMAIL,
                "whatsapp_support": email_settings.WHATSAPP_SUPPORT,
                "service_status": "operational",
                "deep_link_url": test_deep_link,
                "scheme_name": email_settings.SCHEME,
                "app_name": email_settings.APP_NAME,
                "test_details": {
                    "recipient": to_email,
                    "purpose": f"Email service {test_type} test",
                    "environment": (
                        "production" if email_settings.SEND_EMAILS else "development"
                    ),
                    "deep_link_supported": True,
                },
            }

            # Use a simple test template or fallback to welcome template
            if test_tenant:
                template_name = "welcome_tenant"
                subject = f"Email Service Test - {test_type.title()}"
                template_data.update(
                    {
                        "user_name": "Test Recipient",
                        "user_email": to_email,
                        "temporary_password": "test-password-123",
                        "tenant_slug": "test-tenant",
                        "setup_guide_url": email_settings.SETUP_GUIDE_URL,
                        "download_url": email_settings.DOWNLOAD_URL,
                    }
                )
            elif self.template_manager.template_exists("test_email"):
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
                        "deep_link_url": test_deep_link,
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
            "url_scheme_info": {
                "scheme": email_settings.SCHEME,
                "app_name": email_settings.APP_NAME,
                "registered": self.url_handler.is_protocol_registered(),
                "supported_actions": self.url_handler.get_supported_actions(),
            },
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
            # TODO validate against auth service
            # This is a simplified version for demonstration
            import jwt

            # Check token format
            if len(token) < 20:
                return {"valid": False, "error": "Token too short", "can_retry": True}

            # Check if token looks like a JWT
            if len(token) > 100 and token.count(".") == 2:
                # Try to decode JWT
                try:
                    # TODO use SECRET_KEY
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

            # Create a login deep link for the user
            login_deep_link = self.url_handler.create_deep_link("login")

            template_data = {
                "user_name": user_name,
                "reset_time": current_time,
                "clinic_name": email_settings.FROM_NAME,
                "support_email": email_settings.SUPPORT_EMAIL,
                "deep_link_url": login_deep_link,
                "app_name": email_settings.APP_NAME,
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
                "next_steps": [
                    f"Click <a href='{login_deep_link}'>here</a> to log in with your new password",
                    "Review your account security settings",
                    "Update your profile information if needed",
                ],
            }

            logger.info(f"Password reset success notification sent to {user_email}")

            return await self.send_templated_email(
                EmailType.SECURITY_ALERT,
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

    def create_sample_deep_links(self) -> Dict[str, str]:
        """Create sample deep links for testing and documentation"""
        return {
            "login": self.url_handler.create_deep_link("login", tenant="sample-clinic"),
            "reset_password": self.url_handler.create_deep_link(
                "reset-password", token="sample-token-123"
            ),
            "verify_email": self.url_handler.create_deep_link(
                "verify-email", token="verification-token-456"
            ),
            "open_appointment": self.url_handler.create_deep_link(
                "open-appointment", id="appointment-789"
            ),
            "open_patient": self.url_handler.create_deep_link(
                "open-patient", id="patient-101"
            ),
        }


# Global email service instance
email_service = ResendEmailService()
